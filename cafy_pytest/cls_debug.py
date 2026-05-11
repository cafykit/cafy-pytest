import logging
import requests
import traceback
from requests.adapters import HTTPAdapter
from urllib3 import Retry, request
import json
import time
import os
import sys
from debug import DebugLibrary

# CLS metadata: prefer ``dirname(work_dir)/debug_activate/`` (e.g. cafy3-run-992489 when
# CafyLog.work_dir is cafy3-run-992489/2916), else ``work_dir/debug_activate/``.
CLS_DATA_FILE_JSON = "cls_data_file.json"
DEBUG_ACTIVATE_SUBDIR = "debug_activate"

_log = logging.getLogger(__name__)

_TRUTHY_STRINGS = frozenset(("1", "true", "yes", "on", "enabled"))
_FALSEY_STRINGS = frozenset(("0", "false", "no", "off", "disabled", ""))


def _normalize_optional_str(value):
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def parse_cls_enabled(value, default=0):
    """
    Parse CLS flag from os.environ (always strings), JSON, or bool/int.
    Returns 0 or 1 for compatibility with existing ``CLS == 1`` / ``int(CLS)`` usage.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value != 0 else 0
    s = str(value).strip().lower()
    if s in _TRUTHY_STRINGS:
        return 1
    if s in _FALSEY_STRINGS:
        return 0
    try:
        return 1 if int(s, 10) != 0 else 0
    except ValueError:
        return default


def parse_logstash_port_value(value):
    """Return int TCP port or None if unset or invalid."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s, 10)
    except ValueError:
        return None


def _env_cls_defaults():
    cls_val = parse_cls_enabled(os.environ.get("CLS", "0"), default=0)
    cls_host = _normalize_optional_str(os.environ.get("CLS_HOST"))
    logstash_server = _normalize_optional_str(os.environ.get("LOGSTASH_SERVER"))
    logstash_port = _normalize_optional_str(os.environ.get("LOGSTASH_PORT"))
    return cls_val, cls_host, logstash_server, logstash_port


def _env_reg_id():
    return _normalize_optional_str(os.environ.get("REG_ID"))


def _cls_data_file_candidates(work_dir):
    """
    Paths to try for ``cls_data_file.json``, in order.

    Orchestration often writes under the parent of pytest's per-run folder
    (e.g. ``.../cafy3-run-992489/debug_activate/`` while ``work_dir`` is
    ``.../cafy3-run-992489/2916``).
    """
    if not work_dir:
        return []
    ab = os.path.abspath(work_dir)
    rel = os.path.join(DEBUG_ACTIVATE_SUBDIR, CLS_DATA_FILE_JSON)
    out = []
    parent = os.path.dirname(ab)
    if parent and parent != ab:
        out.append(os.path.join(parent, rel))
    out.append(os.path.join(ab, rel))
    return out


def _cls_data_file_path(work_dir):
    """First existing ``cls_data_file.json`` path among :func:`_cls_data_file_candidates`, or ``None``."""
    for path in _cls_data_file_candidates(work_dir):
        if os.path.isfile(path):
            return path
    return None


def _cls_container_ip_port_ready(meta):
    """
    True when container IP and port are both set (either lowercase or CLS_* keys)
    to non-empty values so we can build ``cls_host`` from them; otherwise use
    ``CLS_HOST`` / ``cls_host`` or env (the prior behavior).
    """
    ip = meta.get("cls_container_host_ip")
    if ip is None:
        ip = meta.get("CLS_CONTAINER_HOST_IP")
    port = meta.get("cls_container_host_port")
    if port is None:
        port = meta.get("CLS_CONTAINER_HOST_PORT")
    if not _normalize_optional_str(ip):
        return False
    if port is None:
        return False
    if isinstance(port, str) and not port.strip():
        return False
    return True


def _build_cls_host_from_container(meta):
    """
    Build CLS host URL from ``cls_container_host_ip`` / ``CLS_CONTAINER_HOST_IP`` and
    ``cls_container_host_port`` / ``CLS_CONTAINER_HOST_PORT`` (and optional scheme keys).
    Caller must ensure :func:`_cls_container_ip_port_ready` is true.
    """
    ip = meta.get("cls_container_host_ip")
    if ip is None:
        ip = meta.get("CLS_CONTAINER_HOST_IP")
    port = meta.get("cls_container_host_port")
    if port is None:
        port = meta.get("CLS_CONTAINER_HOST_PORT")
    ip = _normalize_optional_str(ip)
    if not ip:
        return None
    scheme = meta.get("cls_scheme") or meta.get("CLS_SCHEME")
    scheme = _normalize_optional_str(scheme) or "http"
    port_str = _normalize_optional_str(port) if port is not None else None
    if not port_str:
        return "{}://{}".format(scheme, ip)
    return "{}://{}:{}".format(scheme, ip, port_str)


def resolve_cls_configuration(work_dir=None):
    """
    Resolve CLS, CLS_HOST, LOGSTASH_SERVER, LOGSTASH_PORT, and REG_ID.

    - Default: read from environment (CLS as string \"true\"/\"false\"/\"1\"/\"0\", etc.).
    - If ``dirname(work_dir)/debug_activate/cls_data_file.json`` or
      ``work_dir/debug_activate/cls_data_file.json`` exists (first match wins): for each setting, use the file
      only when that variable's key(s) are present in the JSON; otherwise keep the env-based value.
      For ``cls_host``, when the file is used: only if **both** container IP and port are set
      (``cls_container_host_ip`` or ``CLS_CONTAINER_HOST_IP``, and ``cls_container_host_port``
      or ``CLS_CONTAINER_HOST_PORT``), build the URL from those keys; otherwise use ``cls_host`` /
      ``CLS_HOST`` from the file if present, else ``CLS_HOST`` from the environment.
    - If ``CLS`` / ``cls`` is present in the file and ``REG_ID`` / ``reg_id`` is present in the file,
      ``REG_ID`` is taken from the file instead of ``os.environ``.

    Returns:
        tuple: (cls 0|1, cls_host, logstash_server, logstash_port, reg_id)
        ``logstash_port`` is stored as a string when set (same as os.environ) for backward compatibility.
        ``reg_id`` matches prior behavior (from ``REG_ID`` env) unless overridden by the file as above.
    """
    cls_val, cls_host, logstash_server, logstash_port = _env_cls_defaults()
    reg_id = _env_reg_id()
    cls_host_source = "environment (CLS_HOST)" if cls_host else "unset"
    meta_path = _cls_data_file_path(work_dir)
    if meta_path and os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            _log.warning("CLS could not read cls_data_file %s: %s", meta_path, e)
            meta = None
        if isinstance(meta, dict) and meta:
            if "CLS" in meta or "cls" in meta:
                raw = meta["CLS"] if "CLS" in meta else meta["cls"]
                cls_val = parse_cls_enabled(raw, default=cls_val)
            if "LOGSTASH_SERVER" in meta or "logstash_server" in meta:
                ls = meta["LOGSTASH_SERVER"] if "LOGSTASH_SERVER" in meta else meta["logstash_server"]
                logstash_server = _normalize_optional_str(ls)
            if "LOGSTASH_PORT" in meta or "logstash_port" in meta:
                lp = meta["LOGSTASH_PORT"] if "LOGSTASH_PORT" in meta else meta["logstash_port"]
                logstash_port = (
                    _normalize_optional_str(lp) if lp is not None and str(lp).strip() != "" else None
                )
            built = None
            if _cls_container_ip_port_ready(meta):
                built = _build_cls_host_from_container(meta)
            explicit_file_host = None
            if "CLS_HOST" in meta or "cls_host" in meta:
                ch = meta["CLS_HOST"] if "CLS_HOST" in meta else meta["cls_host"]
                explicit_file_host = _normalize_optional_str(ch)
            if built:
                cls_host = built
                cls_host_source = "cls_data_file.json (cls_container_host_ip / CLS_CONTAINER_HOST_IP)"
            elif explicit_file_host:
                cls_host = explicit_file_host
                cls_host_source = "cls_data_file.json (cls_host / CLS_HOST)"
            else:
                cls_host_source = "environment (CLS_HOST)" if cls_host else "unset"
            if ("CLS" in meta or "cls" in meta) and ("REG_ID" in meta or "reg_id" in meta):
                rid = meta["REG_ID"] if "REG_ID" in meta else meta["reg_id"]
                reg_id = _normalize_optional_str(rid)

    if not (logstash_port or logstash_server) and cls_val == 1:
        _log.warning(
            "CLS disabled: LOGSTASH_SERVER and LOGSTASH_PORT are unset while CLS was enabled"
        )
        cls_val = 0

    if cls_host:
        _log.info("CLS cls_host=%s (source: %s)", cls_host, cls_host_source)
    else:
        if cls_val == 1:
            _log.warning(
                "CLS cls_host is not set (source: %s) while CLS is enabled",
                cls_host_source,
            )
        else:
            _log.info("CLS cls_host is not set (source: %s)", cls_host_source)

    return cls_val, cls_host, logstash_server, logstash_port, reg_id


def requests_retry(logger, url, method, data=None, files=None,  headers=None, timeout=None, retry_count=5, **kwargs):
    """ Retry Connection to server and database.

    Args:
        url: String of URL .
        method: String of 'GET', 'POST', 'PUT' or 'DELETE'.
        **kwargs: Other Response arguments

    Examples:
        # without JSON serializer
        _requests_retry(url, 'POST', json=context)
        # with JSON serializer
        _requests_retry(url, 'POST', data=json.dumps(context,
                             default=json_serial))
    """
    retries = Retry(total=retry_count,
                    backoff_factor=1,
                    status_forcelist=[502, 503, 504, 404])
    s = requests.Session()
    s.mount('http://', HTTPAdapter(max_retries=retries))
    s.mount('https://', HTTPAdapter(max_retries=retries))

    response = None
    try:
        if method in ['GET', 'PUT', 'PATCH', 'POST', 'DELETE']:
            #kwargs['headers'] = {'Content-Type': 'application/json'}
            if files:
                kwargs['files'] = files
            if data:
                kwargs['data'] = data
            if headers:
                kwargs['headers'] = headers
            if timeout:
                kwargs['timeout']  = timeout
            response = s.request(method=method, url=url, **kwargs)


        if response.status_code != 200:
            logger.warning("HTTP Status Code: {0}\n{1}"
                              .format(response.status_code, response.text))
    except requests.exceptions.RetryError as e:
        # 5XX Database/SQLAlchemy Error handling
        logger.warning(repr(e))
        logger.warning(traceback.format_exc())
        logger.warning("URL and method: {0}\n{1}"
                       .format(url, method))
        logger.warning("kwargs={}".format(kwargs))
    except requests.exceptions.ConnectionError as e:
        # Server Connection Error
        logger.warning(repr(e))
        logger.warning(traceback.format_exc())
        logger.warning("URL and method: {0}\n{1}"
                       .format(url, method))
        logger.warning("kwargs={}".format(kwargs))
    except Exception as e:
        logger.warning(repr(e))
        logger.warning(traceback.format_exc())
        logger.warning("URL and method: {0}\n{1}"
                       .format(url, method))
        logger.warning("kwargs={}".format(kwargs))
    return response


class DebugAdapter:
    def __init__(self, cls:bool=False,debug:bool=False, **kwargs) -> None:
        """
        Debug Adaptor code for frameworks.
        Args:
            cls (bool, optional): _. Defaults to False.
            debug (bool, optional): _description_. Defaults to False.
            logger (object, optional): _description_. Defaults to None.

        """
        #not used now but needed for future apps.
        self.cls = cls
        self.debug = debug
        self.debug_server = kwargs.get("debug_server", None)
        self.registeration_id = kwargs.get('reg_id', None)
        # cafy input file or simple custom file for debugging..enabled with debug2.0
        self.debug_file = kwargs.get('debug_file', None)
        self.topo_file= kwargs.get('topo_file',None)
        self.test_name = kwargs.get("test_name", None)
        self.logger = kwargs.get('logger', None)
        if not self.logger:
            import logging
            from logging import getLogger
            self.logger = getLogger(__name__)
            log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            log_handler = logging.StreamHandler(stream=sys.stdout)
            log_handler.setFormatter(log_formatter)
            # log_handler.setLevel('debug')
            self.logger.addHandler(log_handler)
    
    def register_test(self):
        """
        Register the test_suite with debug service.
        Upload the topo and debug files, get reg_id if not already set.

        Returns:
            dict of status and error/success string.
        """
        if not self.debug:
            return {"status": None, "msg": "debug is not enabled"}
        if not self.test_name:
            return {"status": None, "msg": "testcase is set None"}        
        params ={
            "test_suite" : self.test_name,
            "test_id" : 0,
            "debug_server_name" : self.debug_server,
            "reg_id" : self.registeration_id
        }
        # Following code is needed for 3.11 and some changes in registeration/collector/analyzer. This is the below erorr.
        # plugin.py:569: ResourceWarning: unclosed file <_io.BufferedReader name='/auto/cafy-sjc/cafy_log/cafy3-run-992104/1923/PP_SFSIM_Fixed_virtual_topo.json'>
        #   response = register_object.register_test()
        # ResourceWarning: Enable tracemalloc to get the object allocation traceback
        # plugin.py:569: ResourceWarning: unclosed file <_io.BufferedReader name='/auto/cafy-sjc/cafy_log/cafy3-run-992104/1923/992104_input_file.json'>
        #   response = register_object.register_test()
        #
        #
        # with open(self.topo_file, 'rb') as f:
        #     topo = f.read()
        # with open(self.debug_file, 'rb') as f:
        #     debug_file = f.read()
        # files = {
        #     'testbed_file': topo,
        #     'input_file' : debug_file
        # }
        files = {
            'testbed_file': open(self.topo_file, 'rb'),
            'input_file' : open(self.debug_file, 'rb')
        }
        reg_dict = {}
        try:
            url = f'http://{self.debug_server}:5001/create/'
            self.logger.info(f'Calling Registration service to register the test execution (url:{url})')
            response = requests_retry(self.logger, url, 'POST', files=files, data=params, timeout = 300)
            if response.status_code == 200:
                #reg_dict will contain testbed, input, debug files and reg_id
                reg_dict = response.text # This reg_dict is a string of dict
                reg_dict = json.loads(reg_dict)
                self.registeration_id = reg_dict['reg_id']
                self.logger.info(f'Registration ID in debug case : {self.registeration_id}')
                return {"status": "OK", "data" : reg_dict}
            else:
                self.logger.info("Registration server returned code %d " % response.status_code)
                return {"status" : None, "msg":f'http call {response.status_code}'}
        except Exception as err:
            self.logger.error(f'Error encountered in registeration process" : {err}')
            return {"status": None, "msg": f'{err}'}
    
    def initiate_analyzer(self,testcase:str):
        """
        Initialize the analyzer per testcase.
        
        Args:
           testcase (str): testcase name 

        Returns:
            boolean : True if analyzer is initiated. False, if error is encountered.
        """
        if not self.debug_server:
            self.logger.info("debug_server name not provided in topo file, Not calling analyzer status")
        else:
            url = f'http://{self.debug_server}:5001/initiate_analyzer/'
            params = {"test_case": testcase,
                  "reg_id": self.registeration_id,
                  "debug_server_name": self.debug_server}
            headers = {'content-type': 'application/json'}
            try:
                self.logger.info(f'Calling registration service (url:{url}) to initialize analyzer')
                response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=300)
                if response.status_code == 200:
                    self.logger.info("Analyzer initialized")
                    return True
                else:
                    self.logger.warning("Analyzer failed %d" % response.status_code)
                    return False
            except Exception as e:
                self.logger.warning(f'Http call to registration service url:{url} is not successful')
                self.logger.warning(f'Error {e}')
                return False

    def analyzer_status(self,testcase:str):
        """
        Get the analyzer status for particular testcase.

        Args:
        headers = {'content-type': 'application/json'}
        params = {"test_case": test_case,
                  "reg_id": reg_id,
                  "debug_server_name": debug_server}
        Returns:
            boolean : true for analyzer is working , false if the check fails.
        """
        if not self.debug_server:
            self.logger.info("debug_server name not provided in topo file, not calling analyzer status")
        else:
            url = f'http://{self.debug_server}:5001/end_test_case/'
            params = {"test_case": testcase,
                  "reg_id": self.registeration_id,
                  "debug_server_name": self.debug_server}
            headers = {'content-type': 'application/json'}
            try:
                self.logger.info(f'Calling registration service (url:{url}) to check analyzer status')
                response = requests_retry(self.logger, url, 'GET', json=params, headers=headers, timeout=30, retry_count=2)
                if response.status_code == 200:
                    return response.json()['analyzer_status']
                else:
                    self.logger.info(f'Analyzer status check failed {response.status_code}')
                    return None
            except Exception as e:
                self.logger.info(f'Http call to registration service url:{url} is not successful')
                self.logger.info(f'Error {e}')
                return None

    def register_testcase(self,testcase_name):  
        """_summary_

        Args:
            testcase_name (_type_): _description_
        """
        if self.registeration_id:
            params = {"testcase_name": testcase_name}
            headers = {'content-type': 'application/json'}
            if self.debug_server is None:
                self.logger.error("debug_server name not provided in topology file")
            else:
                url = f'http://{self.debug_server}:5001/registertest/'
                try:
                    response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=300)
                    if response.status_code == 200:
                        self.logger.info(f'Handshake for {self.registeration_id} for {testcase_name} to registration service successful')
                    else:
                        self.logger.warning(f'Handshake part of registration server returned code {response.status_code}')
                except Exception as e:
                    self.logger.warning(f'Error {e}')
                    self.logger.warning(f'Http call to registration service url:{url} is not successful')

    def collector_call(self, params, headers):
        """_summary_

        Args:
            params (dict) : dictionary of parameters sent to collector service.
            headers (dict): {'content-type': 'application/json'} 

        Returns:
            response or None

        ##this code needs to improve. 
        """
        if self.debug_server is None:
            self.logger.info("debug_server name not provided in topo file")
            return None
        else:
            url = f'http://{self.debug_server}:5001/startdebug/v1/'
            try:
                self.logger.info(f'Calling registration service (url:{url}) to start collecting')
                response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=1500)
                if response.status_code == 200:
                    waiting_time = 0
                    poll_flag = True
                    while(poll_flag):
                        url_status = f'http://{self.debug_server}:5001/collectionstatus/'
                        response = requests_retry(self.logger, url_status, 'POST', json=params, headers=headers, timeout=30)
                        if response.status_code == 200:
                            message = response.json()
                            if message["collector_status"] == True:
                                return response
                            else:
                                time.sleep(30)
                                waiting_time = waiting_time + 30
                                if waiting_time > 900:
                                    poll_flag = False
                        else:
                            poll_flag = False
                            self.logger.info(f'collection status api return status other then 200 response {response.status_code}')
                else:
                    self.logger.warning(f'start_debug part of handshake server returned code {response.status_code}')
                    return None
            except Exception as e:
                self.logger.warning(f'Error {e}')
                self.logger.warning(f'Http call to registration service url:{url} is not successful')
                return None
           
    def collector_call_snapshot(self, params, headers):
        """_summary_
        This function initiates a data snapshot collection process.
        It then polls a status endpoint to monitor the collection's completion.

        Args:
            params (dict) : dictionary of parameters sent to collector service.
            headers (dict): {'content-type': 'application/json'}

        Returns:
            response or None

        """
        if self.debug_server is None:
            self.logger.info("debug_server name not provided in topo file")
            return None
        else:
            url = f'http://{self.debug_server}:5001/startsnapshot/'
            try:
                self.logger.info(f'Calling registration service (url:{url}) to start collecting')
                response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=2700)
                if response.status_code == 200:
                    waiting_time = 0
                    poll_flag = True
                    while(poll_flag):
                        # Changed from /collectionstatus/ to /snapshotstatus/ as requested
                        url_status = f'http://{self.debug_server}:5001/snapshotstatus/'
                        response = requests_retry(self.logger, url_status, 'POST', json=params, headers=headers, timeout=30)
                        if response.status_code == 200:
                            message = response.json()
                            if message["snapshot_status"] == True: # Assuming "collector_status" key remains relevant for snapshot status
                                return response
                            else:
                                time.sleep(90)
                                waiting_time = waiting_time + 90
                                if waiting_time > 2700:
                                    poll_flag = False
                        else:
                            poll_flag = False
                            self.logger.info(f'collection status api return status other then 200 response {response.status_code}')
                else:
                    self.logger.warning(f'start_debug part of handshake server returned code {response.status_code}')
                    return None
            except Exception as e:
                self.logger.warning(f'Error {e}')
                self.logger.warning(f'Http call to registration service url:{url} is not successful')
                return None

    def rc_call(self, params, headers):
        """_summary_

        Args:
            params (dict) : dictionary of parameters sent to Rootcause service.
            headers (dict): {'content-type': 'application/json'} 

        Returns:
           None or respone.
        
        # this code also needs to improve.
        """
        if self.debug_server is None:
            self.logger.info(f'debug_server name not provided in topo file')
            return None
        else:
            url = f'http://{self.debug_server}:5001/startrootcause/'
            try:
                self.logger.info("Calling RC engine to start rootcause (url:%s)" % url)
                response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=600)
                if response.status_code == 200:
                    return response
                else:
                    self.logger.warning(f'startrootcause part of RC engine returned code {response.status_code}')
                    return None
            except Exception as e:
                self.logger.warning(f'Error {e}')
                self.logger.warning(f'Http call to root cause service url:{url} is not successful')
                return None

    def analyzer_log(self, work_dir:str):
        """_summary_

        Args:
            work_dir (string): _description_
        """
        params = {"reg_id": self.registeration_id,
                  "debug_server_name": self.debug_server}
        url = f'http://{self.debug_server}:5001/get_analyzer_log/'
        try:
            response = requests_retry(self.logger, url, 'GET', data=params, timeout=300)
            if response is not None and response.status_code == 200:
                if response.text:
                    if 'Content-Disposition' in response.headers:
                        analyzer_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                        analyzer_log_file_full_path = os.path.join(work_dir, analyzer_log_filename)
                        with open(analyzer_log_file_full_path, 'w') as f:
                            f.write(response.text)
                            self.logger.info(f'{analyzer_log_filename} saved at {work_dir}')
                    else:
                        self.logger.info("No analyzer log file received")
        except Exception as e:
            self.logger.warning(f'Error {e}')
            self.logger.info('No Analyzer log file receiver')
    
    def collector_log(self, params:dict, headers:dict, work_dir:str):
        """_summary_

        Args:
            params (dict) = {"reg_id": registeration id,
                      "topo_file": topo file,
                      "input_file": debug file}
            headers (dict) = {'content-type': 'application/json'}
            work_dir (str): _description_
        """
        try:
            url = f'http://{self.debug_server}:5001/uploadcollectorlogfile/'
            self.logger.info(f'Calling registration upload collector logfile service (url:{url})')
            response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=300)
            if response is not None and response.status_code == 200:
                if response.text:
                    summary_log = response.text
                    if '+'*120 in response.text:
                        summary_log, verbose_log = response.text.split('+'*120)
                    self.logger.info (f'Debug Collector logs: {summary_log}')
                    if 'Content-Disposition' in response.headers:
                        debug_collector_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                        collector_log_file_full_path = os.path.join(work_dir,debug_collector_log_filename)
                        with open(collector_log_file_full_path, 'w') as f:
                            f.write(response.text)
                        try:
                            DebugLibrary.convert_collector_logs_to_json(collector_log_file_full_path)
                        except:
                            self.logger.info("Failed to convert collector logs to json")
                    else:
                        self.logger.info("No collector log file received")

            url = f'http://{self.debug_server}:5001/deleteuploadedfiles/'
            self.logger.info(f'Calling registration delete upload file service (url:{url}')
            response = requests_retry(self.logger, url, 'POST', json=params, headers=headers, timeout=300)
            if response.status_code == 200:
                self.logger.info("Topology and input files deleted from registration server")
            else:
                self.logger.info("Error in deleting topology and input files from registration server")
        except Exception as e:
            self.logger.warning("Error {}".format(e))
            self.logger.info("Error in uploading collector logfile")


class ClsAdapter:
    def __init__(self,cls_host, reg_id, **kwargs) -> None:
        self.cls_host = cls_host
        self.reg_id = reg_id
        self.logger = kwargs.get('logger', None)
        if not self.logger:
            import logging
            from logging import getLogger
            self.logger = getLogger(__name__)
            log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            log_handler = logging.StreamHandler(stream=sys.stdout)
            log_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_handler)

    def update_cls_testcase(self, test_case):
        '''
        update cls with test case change update
        :param testcase:
        :return: Boolean for able to succeed to inform CLS for testcase change.
        '''
        url = f'{self.cls_host}/api/collector/{self.reg_id}/case-update'
        try:
            params ={
                   "case_name" : test_case
            }
            self.logger.info("CLS case-update: url=%s testcase=%s", url, test_case)
            response = requests_retry(self.logger, url, 'PUT', json=params, timeout=300)
            if response.status_code == 200:
                self.logger.info("cls notified")
                return True
            else:
                self.logger.warning(f'cls notification failed {response.status_code}')
                return False
        except Exception as e:
            self.logger.warning(f'Http call to cls service url:{url} is not successful')
            self.logger.warning("Error {}".format(e))
            return False


