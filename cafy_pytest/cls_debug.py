import requests
import traceback
from requests.adapters import HTTPAdapter
from urllib3 import Retry
import json
import time
import os
from debug import DebugLibrary


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
        """_summary_

        Args:
            cls (bool, optional): _description_. Defaults to False.
            debug (bool, optional): _description_. Defaults to False.
            logger (object, optional): _description_. Defaults to None.
        """
        self.cls = cls
        self.debug = debug
        self.debug_server = kwargs.get("debug_server", None)
        self.registeration_id = kwargs.get('reg_id', None)
        self.debug_file = kwargs.get('debug_file', None)
        self.topo_file= kwargs.get('topo_file',None)
        self.test_name = kwargs.get("test_name", None)
        self.logger = kwargs.get('logger', None)
        if not self.logger:
            import logging
            from logging import getLogger
            self.logger = getLogger(__name__)
            log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            log_handler = logging.StreamHandler('stdout')
            log_handler.setFormatter(log_formatter)
            # log_handler.setLevel('debug')
            self.logger.addHandler(log_handler)
    
    def register_test(self):
        if not self.debug:
            return {"status": None, "msg": "debug is not enabled"}
        if not self.test_name:
            return {"status": None, "msg": "testcase is set None"}        
        params ={
            "test_suite" : self.test_name,
            "test_id" : 0,
            "debug_Server_name" : self.debug_server,
            "reg_id" : self.registeration_id
        }
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
                registration_id = reg_dict['reg_id']
                self.logger.info("Registration ID: %s" %registration_id)
                return {"status": "OK", "data" : reg_dict}
            else:
                self.logger.info("Registration server returned code %d " % response.status_code)
                return {"status" : None, "msg":f'http call {response.status_code}'}
        except Exception as err:
            self.logger.error(f'Error encountered in registeration process" : {err}')
            return {"status": None, "msg": f'{err}'}
    
    def initiate_analyzer(self,params,headers):
        if not self.debug_server:
            self.log.info("debug_server name not provided in topo file, Not calling analyzer status")
        else:
            try:
                url = f'http://{self.debug_server}:5001/initiate_analyzer/'
                self.log.info(f'Calling registration service (url:{url}) to initialize analyzer')
                response = requests_retry(self.log, url, 'POST', data=params, timeout=300)
                if response.status_code == 200:
                    self.log.info("Analyzer initialized")
                    return True
                else:
                    self.log.warning("Analyzer failed %d" % response.status_code)
                    return False
            except Exception as e:
                self.log.warning("Http call to registration service url:%s is not successful" % url)
                self.log.warning("Error {}".format(e))
                return False

    def analyzer_status(self,params,headers):
        if not self.debug_server:
            self.logger.info("debug_server name not provided in topo file, not calling analyzer status")
        else:
            try:
                url = f'http://{self.debug_server}:5001/end_test_case/'
                self.logger.info(f'Calling registration service (url:{url}) to check analyzer status')
                response = requests_retry(self.logger, url, 'GET', data=params, timeout=30, retry_count=2)
                if response.status_code == 200:
                    return response.json()['analyzer_status']
                else:
                    self.log.info("Analyzer status check failed %d" % response.status_code)
                    return None
            except Exception as e:
                self.logger.info("Http call to registration service url:%s is not successful" % url)
                self.logger.info("Error {}".format(e))
                return None

    def register_testcase(self,testcase_name):       
        if self.registeration_id:
            params = {"testcase_name": testcase_name}
            headers = {'content-type': 'application/json'}
            if self.debug_server is None:
                self.log.error("debug_server name not provided in topology file")
            else:
                try:
                    url = f'http://{self.debug_server}:5001/registertest/'
                    response = requests_retry(self.log, url, 'POST', json=params, headers=headers, timeout=300)
                    if response.status_code == 200:
                        self.log.info(f'Handshake for {self.registration_id} for {testcase_name} to registration service successful')
                    else:
                        self.log.warning(f'Handshake part of registration server returned code {response.status_code}')
                except Exception as e:
                    self.log.warning(f'Error {e}')
                    self.log.warning(f'Http call to registration service url:{url} is not successful')

    def collector_call(self, params, headers):
        if self.debug_server is None:
            self.log.info("debug_server name not provided in topo file")
            return None
        else:
            try:
                url = f'http://{self.debug_server}:5001/startdebug/v1/'
                self.log.info(f'Calling registration service (url:{url}) to start collecting')
                response = requests_retry(self.log, url, 'POST', json=params, headers=headers, timeout=1500)
                if response.status_code == 200:
                    waiting_time = 0
                    poll_flag = True
                    while(poll_flag):
                        url_status = f'http://{self.debug_server}:5001/collectionstatus/'
                        response = requests_retry(self.log, url_status, 'POST', json=params, headers=headers, timeout=30)
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
                            self.log.info(f'collection status api return status other then 200 response {response.status_code}')
                else:
                    self.log.warning(f'start_debug part of handshake server returned code {response.status_code}')
                    return None
            except Exception as e:
                self.log.warning(f'Error {e}')
                self.log.warning(f'Http call to registration service url:{url} is not successful')
                return None

    def rc_call(self, params, headers):
        if self.debug_server is None:
            self.log.info(f'debug_server name not provided in topo file')
            return None
        else:
            try:
                url = f'http://{self.debug_server}:5001/startrootcause/'
                self.log.info("Calling RC engine to start rootcause (url:%s)" % url)
                response = requests_retry(self.log, url, 'POST', json=params, headers=headers, timeout=600)
                if response.status_code == 200:
                    return response
                else:
                    self.log.warning(f'startrootcause part of RC engine returned code {response.status_code}')
                    return None
            except Exception as e:
                self.log.warning(f'Error {e}')
                self.log.warning(f'Http call to root cause service url:{url} is not successful')
                return None

    def analyzer_log(self, work_dir):
        params = {"reg_id": self.registration_id,
                  "debug_server_name": self.debug_server}
        url = f'http://{self.debug_server}:5001/get_analyzer_log/'
        try:
            response = requests_retry(self.log, url, 'GET', data=params, timeout=300)
            if response is not None and response.status_code == 200:
                if response.text:
                    if 'Content-Disposition' in response.headers:
                        analyzer_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                        analyzer_log_file_full_path = os.path.join(work_dir, analyzer_log_filename)
                        with open(analyzer_log_file_full_path, 'w') as f:
                            f.write(response.text)
                            self.log.info(f'{analyzer_log_filename} saved at {work_dir}')
                    else:
                        self.log.info("No analyzer log file received")
        except Exception as e:
            self.log.warning(f'Error {e}')
            self.log.info('No Analyzer log file receiver')
    
    def collector_log(self, params, headers, work_dir):
        try:
            url = f'http://{self.debug_server}:5001/uploadcollectorlogfile/'
            self.log.info(f'Calling registration upload collector logfile service (url:{url})')
            response = requests_retry(self.log, url, 'POST', json=params, headers=headers, timeout=300)
            if response is not None and response.status_code == 200:
                if response.text:
                    summary_log = response.text
                    if '+'*120 in response.text:
                        summary_log, verbose_log = response.text.split('+'*120)
                    self.log.info (f'Debug Collector logs: {summary_log}')
                    if 'Content-Disposition' in response.headers:
                        debug_collector_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                        collector_log_file_full_path = os.path.join(work_dir,debug_collector_log_filename)
                        with open(collector_log_file_full_path, 'w') as f:
                            f.write(response.text)
                        try:
                            DebugLibrary.convert_collector_logs_to_json(collector_log_file_full_path)
                        except:
                            self.log.info("Failed to convert collector logs to json")
                    else:
                        self.log.info("No collector log file received")

            url = f'http://{self.debug_server}:5001/deleteuploadedfiles/'
            self.log.info(f'Calling registration delete upload file service (url:{url}')
            response = requests_retry(self.log, url, 'POST', json=params, headers=headers, timeout=300)
            if response.status_code == 200:
                self.log.info("Topology and input files deleted from registration server")
            else:
                self.log.info("Error in deleting topology and input files from registration server")
        except Exception as e:
            self.log.warning("Error {}".format(e))
            self.log.info("Error in uploading collector logfile")


class ClsAdapter:
    def __init__(self,cls_host, reg_id, **kwargs) -> None:
        self.cls_host = cls_host
        self.reg_id = reg_id
        self.log = kwargs.get("logger")
        if not self.log:
            from logging import getLogger
            self.log = getLogger(__name__)
            log_formatter = self.log.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            log_handler = self.log.StreamHandler('stdout')
            log_handler.setFormatter(log_formatter)
            log_handler.setLevel(self.logger.DEBUG)

    def update_cls_testcase(self, test_case):
        '''
        update cls with test case change update
        :param testcase:
        :return:
        '''
        try:
            url = "{0}/api/collector/{1}/case-update".format(self.cls_host, self.registration_id)
            params ={
                   "case_name" : test_case
            }
            self.log.info("Calling cls service (url:%s) for testcase" % test_case)
            response = requests_retry(self.log, url, 'PUT', json=params, timeout=300)
            if response.status_code == 200:
                self.log.info("cls notified")
                return True
            else:
                self.log.warning("cls notification failed %d" % response.status_code)
                return False
        except Exception as e:
            self.log.warning("Http call to cls service url:%s is not successful" % url)
            self.log.warning("Error {}".format(e))
            return False


