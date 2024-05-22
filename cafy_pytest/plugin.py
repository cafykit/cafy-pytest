'''
This plugin will cover all the cafy related plugin like email report
'''

import getpass
import html
import inspect
import json
import os
import re
import platform
import shutil
import signal
import smtplib
import socket
import subprocess
import sys
import time
import traceback
import zipfile
from collections import namedtuple, OrderedDict, defaultdict
from configparser import ConfigParser
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE
from enum import Enum
from shutil import copyfile

import allure
import pytest
import requests
import validators
import yaml
import _pytest
from jinja2 import Template
from requests.adapters import HTTPAdapter
from tabulate import tabulate
from urllib3 import Retry
from _pytest.terminal import TerminalReporter
from _pytest.runner import runtestprotocol

# Cafykit imports
from logger.cafylog import CafyLog
from topology.topo_mgr.topo_mgr import Topology
from utils.cafyexception import CafyException
from utils.collectors.confest import Config

from .cafy import Cafy
from .cafy_pdb import CafyPdb
from .cafypdb_config import CafyPdb_Configs
from .cls_debug import DebugAdapter, ClsAdapter


collection_setup = Config()
#Check with CAFYKIT_HOME or GIT_REPO or CAFYAP_REPO environment is set,
#if all are set, CAFYAP_REPO takes precedence
CAFY_REPO = os.environ.get("CAFYAP_REPO", None)
CLS = os.environ.get("CLS", None)
cls_host = os.environ.get("CLS_HOST", None)
LOGSTASH_SERVER = os.environ.get("LOGSTASH_SERVER", None)
LOGSTASH_PORT = os.environ.get("LOGSTASH_PORT", None)


setattr(pytest,"allure",Cafy)

if CAFY_REPO is None:
    #If CAFYAP_REPO is not set, check if GIT_REPO or CAFYKIT_HOME is set
    #If both GIT_REPO and CAFYKIT_HOME are set, CAFYKIT_HOME takes precedence
    CAFY_REPO = os.environ.get("CAFYKIT_HOME", None)
    if CAFY_REPO:
        os.environ['CAFY_REPO'] = CAFY_REPO
    else:
        CAFY_REPO = os.environ.get("GIT_REPO", None)
        if CAFY_REPO:
            if os.path.exists(os.path.join(CAFY_REPO, 'work', 'pytest_cafy_config.yaml')):
                # CAFY_REPO variable has been set to correct repo.
                os.environ['CAFY_REPO'] = CAFY_REPO
            else:
                msg = 'GIT_REPO has not been set to correct repo.'
                pytest.exit(msg)
else:
    os.environ['CAFY_REPO'] = CAFY_REPO

if not CAFY_REPO:
    msg = "Please set the environment variable GIT_REPO or CAFYKIT_HOME or CAFYAP_REPO "
    pytest.exit(msg)


cafy_args = os.environ.get('CAFY_ARGS')
if cafy_args:
    config = ConfigParser() # instantiate
    config.read(cafy_args) # parse existing file
    config_sections = config.sections()

class _CafyConfig:
    allure_server = "file://"
    summary = {}

@pytest.hookimpl(tryfirst=True)
def pytest_addoption(parser):
    setattr(pytest,"cafy",Cafy)

    yml = load_config_file()
    if 'email' in yml:
        email = yml['email']
        email_from = email.get('from')
        email_list = getpass.getuser()
        if 'domain' in email:
            email_list = "%s@%s" % (email_list, email['domain'])
            email_list = [email_list]
        try:
            smtp_server = email['via']['server']
            smtp_port = email['via']['port']
        except:
            smtp_server = 'localhost'
            smtp_port = 25
    else:
        email_from = None
        email_list = None
        smtp_server = 'localhost'
        smtp_port = 25
    if 'web' in yml:
        _CafyConfig.allure_server=yml['web'].get('server',"file://")

    group = parser.getgroup('Email Options')
    group.addoption('--mail-to', action='store', dest='email_list',
                    default=email_list, type=str, nargs='*',
                    help='send the email to specified email addresses')
    group.addoption('--mail-from', action='store', dest='email_from',
                    default=email_from,
                    help='email id with which email will be sent')
    group.addoption('--mail-from-passwd', action='store',
                    dest='email_from_passwd',
                    default=None,
                    help='password of email id given in --mailfrom')
    group.addoption('--smtp-server', action='store', dest='smtp_server',
                    default=smtp_server,
                    help='smtp server ip address/dns name e.g 127.0.0.1 or '
                         'localhost')
    group.addoption('--smtp-port', action='store', dest='smtp_port',
                    default=smtp_port, type=int,
                    help='smtp server port e.g 25')
    group.addoption('--no-email', dest='no_email', action='store_true',
                    help='if specified no email will be sent')
    group.addoption('--mail-if-fail', dest='mail_if_fail', action='store_true',
                    help='if specified, email will be sent only total testcase = passed testcases')

    group = parser.getgroup('Terminal Reporting')
    group.addoption('--no-detail-message', dest='no_detail_message', action='store_true',
                    help='if specified error messages will not be part of terminal summary')

    group = parser.getgroup('Report Directories')
    group.addoption('--work-dir', dest="workdir", metavar="DIR", default=None,
                    help="Path for work dir")

    group.addoption('-R','--report-dir', dest="reportdir",
                    metavar="DIR",
                    default=None,
                    help="Path for report dir")

    group = parser.getgroup('Testbed Options')
    group.addoption('-T', '--topology-file', action='store', dest='topology_file',
                    metavar='topology_file',
                    type=lambda x: is_valid_param(x, file_type='topology_file'),
                    help='Filename of your testbed')

    group.addoption('-I', '--test-input-file', action='store', dest='test_input_file',
                    metavar='test_input_file',
                    type=lambda x: is_valid_param(x, file_type='input_file'),
                    help='Filename of your test input file')

    group.addoption('--tag-file', action='store', dest='tag_file',
                    metavar='tagmap_file',
                    type=lambda x: is_valid_param(x, file_type='tagmap_file'),
                    help='Filename of your tag map')

    group.addoption('--selective-test-file', action='store', dest='selective_test_file',
                    metavar='selective_test_file',
                    type=lambda x: is_valid_param(x, file_type='selective_test_file'),
                    help='Filename of your selective testcases')

    group.addoption('--commit-check', dest='commit_check', action='store_true',
                    help='Variable to set commit check option, default is False')

    group.addoption('--enable-live-update', dest='enable_live_update', action='store_true',
                    help='Variable to enable live logging the status of testcases, default is False')

    group.addoption('-M', '--feature-lib-mode', type=str,
                    choices=("cli", "ydk", "oc", "hybrid_ydk", "hybrid_oc"), dest='feature_lib_mode',
                    metavar='feature_lib_mode', help='Feature library mode')

    group.addoption('-D', "--unset-feature-lib-mode", action='store_true', dest='unset_feature_lib_mode',
                    help='Variable to unset feature_lib_mode set by -M arg, default is False')

    group = parser.getgroup('Cafykit Debug ')
    group.addoption('--debug-enable', dest='debug_enable', action='store_true',
                    help='Variable to enable cafykit debug, default is False')

    group = parser.getgroup('Script Arguments')
    group.addoption('--script-args', action='store', dest='script_args',
                    metavar='script_args', default="{'__nothing__': None}",
                    type=lambda x: is_valid_cafyarg(x),
                    help=' For your additional cafy arguments, A yaml file or\
                     a string of dict')

    group = parser.getgroup('Giso Directory Arguments')
    group.addoption('--giso-dir', dest='giso_dir', metavar='DIR', default=None,
                    help='Path for Giso Directory')

    group = parser.getgroup('Mongo Device')
    group.addoption('--mongo-learn', dest='mongo_learn', action='store_true',
                    help='Variable to enable mongo learning, default is False')
    group.addoption('--mongo-read', dest='mongo_read', action='store_true',
                    help='Variable to enable mongo read, default is False')
    group.addoption('--mongo-mode', action='store', dest='mongo_mode',
            metavar='mongo_mode',
            help='Variable to enable mongo read/write, default is None')

    group.addoption('--collection', action='store', dest='collection',
            type=str, nargs='+', default=[],
            help='For additional cafy arguments to enable collection')

    group = parser.getgroup('Cafy PDB ')
    group.addoption('--cafypdb', dest='cafypdb', action='store_true',
                    help='Variable to enable cafy PDB, default is False')


def is_valid_param(arg, file_type=None):
    if not arg:
        pytest.exit("%s not provided!" % file_type)
    if not os.path.exists(arg):
        #If not a valid file, check if it is a valid url
        if validators.url(arg):
            return arg
        else:
            pytest.exit("%s either doesn't exist or is an invalid url!" % arg)
    else:
        # pytest.topology_file = arg # Set the global namespace variable
        return arg  # It is important to add a return statement, if not given,
        # by default, it returns None and then your
        # config.option.topology_file will be set to None
        # return open(arg, 'r')  # return an open file handle


def is_valid_cafyarg(arg):
    #if block is executed when arg is not a file,instead it is string of dict
    if not os.path.exists(arg):
        eval(arg)
        argdict = yaml.safe_load(arg)
        CafyLog.script_args = argdict
    else:
        #else block is executed when arg is a file
        script_arg_file = is_valid_param(arg)
        CafyLog.script_args = script_arg_file
    return arg


def load_config_file(filename=None):
    _filename = filename
    if not _filename:
        git_repo = os.getenv("GIT_REPO", None)
    if git_repo:
        try:
            _filename = os.path.join(
                git_repo, "work", "pytest_cafy_config.yaml")
            with open(_filename, 'r') as stream:
                return (yaml.safe_load(stream))
        except:
            return {}

def is_jsonable(val):
    try:
        json.dumps(val)
        return True
    except:
        return False

def _requests_retry(logger, url, method, data=None, files=None,  headers=None, timeout=None, retry_count=5, **kwargs):
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

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config._environment = []
    email_list = config.option.email_list
    email_from = config.option.email_from
    email_from_passwd = config.option.email_from_passwd
    smtp_server = config.option.smtp_server
    smtp_port = config.option.smtp_port
    no_email = config.option.no_email
    no_detail_message = config.option.no_detail_message
    #setting the debug_enable.
    cafykit_debug_enable = config.option.debug_enable
    CafyLog.topology_file = config.option.topology_file
    CafyLog.test_input_file = config.option.test_input_file
    CafyLog.tag_file = config.option.tag_file
    CafyLog.mongomode=config.option.mongo_mode
    CafyLog.giso_dir = config.option.giso_dir
    script_list = config.option.file_or_dir
    collection_list = []
    for item in config.option.collection:
        collection_list.extend(item.split(","))
    cafypdb = config.option.cafypdb
    # register additional markers
    config.addinivalue_line("markers", "Future(name): mark test that are planned for future")
    config.addinivalue_line("markers", "Feature(name): mark feature of a testcase")
    config.addinivalue_line("markers", "autofail(name): mark test to Fail when  this testcase has triggered autofail condition")

    if script_list:
        script_path = script_list[0]
        if '::' in script_path:
            script_path = script_path.split('::')[0]
        CafyLog.script_path = os.path.abspath(script_path)

        script_name = os.path.basename(script_list[0]).replace('.py', '')
        #If someone gives the script in the format
        #moduleName::className::testcaseName to execute only a specific testcase
        if '::' in script_name:
            script_name = script_name.split('::')[0]
        CafyLog.module_name = script_name
        _current_time = get_datentime()
        pid = os.getpid()
        work_dir_name = "%s_%s_p%s" % (script_name,_current_time, pid )

        if not config.option.reportdir:
            #If workdir option is set, execute the if block and if not given,
            #execute the else block where the workdir will be set to
            #GIT_REPO/work/archive
            if config.option.workdir:
                if os.path.exists(config.option.workdir):
                    custom_workdir = config.option.workdir
                    work_dir = custom_workdir
                else:
                    print('workdir path not found: {}'.format(config.option.workdir))
                    pytest.exit('workdir path not found')
            else:
                if CAFY_REPO:
                    work_dir = os.path.join(CAFY_REPO, 'work', "archive", work_dir_name)
        else:
            if os.path.exists(config.option.reportdir):
                work_dir = os.path.join(config.option.reportdir, work_dir_name)
            else:
                print('reportdir path not found: {}'.format(config.option.reportdir))
                pytest.exit('reportdir path not found')

        CafyLog.work_dir = work_dir
        #Set CafyLog.work_dir option for all.log
        CafyLog.work_dir = work_dir
        _setup_env()

        config.option.allure_report_dir=os.path.join(CafyLog.work_dir,"allure")
        #Copy topology-file if given to work_dir
        if config.option.topology_file:
            if os.path.exists(config.option.topology_file):
                topo_file = os.path.abspath(config.option.topology_file)
                topo_filename = os.path.basename(config.option.topology_file)
                topo_file_path = os.path.join(work_dir, topo_filename)
                copyfile(config.option.topology_file, topo_file_path)
                os.chmod(topo_file_path, 0o775)

                #If topology_file is given, and  attribute is present,
                #then, save this attibute in a variable called debug_server which will be
                #host to run debug services like registrationa and collector
                topo_obj = Topology(CafyLog.topology_file)


                ### This is needed for local runs or local instances of debug-engine or CLS.
                debug_server = topo_obj.get_debug_server_name()
                logstash_port = topo_obj.get_logstash_port()
                logstash_server_name = topo_obj.get_logstash_server_name()

                if logstash_server_name is not None:
                    CafyLog.logstash_server = logstash_server_name
                if logstash_port is not None:
                    CafyLog.logstash_port = logstash_port
                if debug_server is not None:
                    CafyLog.debug_server = debug_server
                    log = CafyLog("cafy")
                    log.info("CafyLog.debug_server : %s" %CafyLog.debug_server )
                ### till here/.
            else:
                #TODO: Address how u want to save topo file to archive if it is an url
                topo_file = None
        else:
            topo_file = None

        if config.option.test_input_file:
            test_input_file = os.path.abspath(config.option.test_input_file)
            test_input_filename = os.path.basename(config.option.test_input_file)
            test_input_file_path = os.path.join(work_dir, test_input_filename)
            copyfile(config.option.test_input_file, test_input_file_path)
            os.chmod(test_input_file_path, 0o775)

        if config.option.tag_file:
            tag_file = os.path.abspath(config.option.tag_file)
            tag_filename = os.path.basename(config.option.tag_file)
            tag_file_path = os.path.join(work_dir, tag_filename)
            copyfile(config.option.tag_file, tag_file_path)
            os.chmod(tag_file_path, 0o775)

        if config.option.selective_test_file:
            selective_test_file = os.path.abspath(config.option.selective_test_file)
            selective_test_filename = os.path.basename(config.option.selective_test_file)
            selective_test_file_path = os.path.join(work_dir, selective_test_filename)
            copyfile(config.option.selective_test_file, selective_test_file_path)
            os.chmod(selective_test_file_path, 0o775)

        #Copy script-args file or dict (converted to file) if given on cmd line
        #to work_dir, if script-args is not given, config.option.script_args  is set to
        # "{'__nothing__': None}"
        if config.option.script_args:
            if not config.option.script_args == "{'__nothing__': None}":
                temp_arg = config.option.script_args
                script_args_filename = os.path.basename(config.option.script_args)
                if os.path.exists(temp_arg):
                    script_args_path = os.path.join(work_dir, script_args_filename)
                    copyfile(config.option.script_args, script_args_path)
                    os.chmod(script_args_path, 0o775)
                #if dict is given, convert that to file and do the copy
                else:
                    with open(os.path.join(os.path.sep, work_dir, "scriptargs"), "w") as f:
                        f.write(temp_arg)

        #Copy junitxml file name to workdir if --junitxml option is provided
        if config.option.xmlpath:
            os.environ['junitxml'] = config.option.xmlpath

        #Set respective environ variables if one of the 2 options mongo-learn or
        #mongo-read are given on cmd line. Both options cannot coexist
        if config.option.mongo_learn and config.option.mongo_read:
            pytest.exit('Both options mongo-learn & mongo-read cannot coexist!')
        elif config.option.mongo_learn:
            os.environ['cafykit_mongo_learn'] = 'True'
        elif config.option.mongo_read:
            os.environ['cafykit_mongo_read'] = 'True'

        if config.option.commit_check:
            CafyLog.commit_check = True

        if config.option.feature_lib_mode:
            if config.option.feature_lib_mode == "hybrid_ydk":
                os.environ["feature_lib_mode"] = "hybrid"
                os.environ["hybrid_mode"] = "ydk"
            elif config.option.feature_lib_mode == "hybrid_oc":
                os.environ['feature_lib_mode'] = "hybrid"
                os.environ["hybrid_mode"] = "oc"
            elif config.option.feature_lib_mode in ("cli", "ydk", "oc"):
                os.environ["feature_lib_mode"] = config.option.feature_lib_mode

        if config.option.unset_feature_lib_mode:
            #unset both env variables: 'feature_lib_mode' and 'hybrid_mode'
            if os.environ.get("feature_lib_mode", None):
                del os.environ["feature_lib_mode"]
            if os.environ.get("hybrid_mode", None):
                del os.environ["hybrid_mode"]

        #Debug Registration Server code
        #Cant introduce switch case as this plugin is common for 3.6 and 3.11 env.
        call_registeration = False
        if CLS and not cafykit_debug_enable :
            call_registeration = False
            reg_id = os.environ.get("REG_ID", None)
            CafyLog.logstash_server = LOGSTASH_SERVER
            CafyLog.logstash_port = int(LOGSTASH_PORT)
            #set the debug_server to be NONE.
            CafyLog.debug_server = None
        elif CLS and cafykit_debug_enable:
            call_registeration = True
            reg_id = os.environ.get("REG_ID", None)
            CafyLog.logstash_server = LOGSTASH_SERVER
            CafyLog.logstash_port = int(LOGSTASH_PORT)
            if not CafyLog.debug_server:
                call_registeration = False
        elif not CLS and cafykit_debug_enable:
            call_registeration=True
            reg_id = None
        else:
            #unset everything.
            CafyLog.debug_server = None
            CafyLog.logstash_server = None
            CafyLog.logstash_port = None
            reg_id = None
        
        reg_dict = {}
        if call_registeration:
            kwargs = {
                    'reg_id': reg_id,
                    'debug_file': CafyLog.test_input_file,
                    'topo_file' : CafyLog.topology_file,
                    'test_name' : script_name,
                    'debug_server' : CafyLog.debug_server
            }
            ## Only needed in case if debug is enabled.

            from .cls_debug import DebugAdapter
            global register_object
            register_object = DebugAdapter(debug=cafykit_debug_enable,cls=CLS,logger=None, kwargs=kwargs)
            response = register_object.register_test()
            if response['status'] != "OK":
                log.info(f'register response",{response["msg"]}')
            else:
                log.info(f'CLS enable : {CLS}')
                log.info(f'Debug Enable : f{cafykit_debug_enable}')
                log.info(f'reg_id dict : {reg_dict}')
                reg_dict = response['data']
                CafyLog.registration_id = reg_dict['reg_id']
                with open(os.path.join(CafyLog.work_dir, "cafy_reg_id.txt"), "w") as f:
                                f.write(reg_dict['reg_id'])
        
        config._email = EmailReport(email_list,
                                    email_from,
                                    email_from_passwd,
                                    smtp_server,
                                    smtp_port,
                                    no_email,
                                    no_detail_message,
                                    topo_file,
                                    script_list,
                                    reg_dict,
                                    collection_list,
                                    cafypdb)
        config.pluginmanager.register(config._email)

        #Write all.log path to terminal
        reporter = TerminalReporter(config, sys.stdout)
        #reporter.write_line("all.log location: %s" %CafyLog.work_dir)
        reporter.write_line("Virtual Env: %s" %(os.getenv("VIRTUAL_ENV")))
        reporter.write_line("Complete Log Location: %s/all.log" %CafyLog.work_dir)
        reporter.write_line("Registration Id: %s" % CafyLog.registration_id)

def pytest_unconfigure(config):
    email = getattr(config, '_email', None)
    if email:
        del config._email
        config.pluginmanager.unregister(email)
    # removed the env set by this plugins
    arc_dir = 'ARCHIVE_DIR'
    if os.environ.get(arc_dir):
        #print ('removing env: ARCHIVE_DIR')
        os.environ[arc_dir] = ''
    try:
        # Copy all environment variables into a env.txt named file and
        # save it in work_dir
        tmp_text = dict(os.environ)
        tmp_str_text = str(tmp_text)
        with open(os.path.join(CafyLog.work_dir, "env.txt"), "w") as f:
            f.write(tmp_str_text)
    except:
        pass

def pytest_generate_tests(metafunc):

    """
    count = metafunc.config.option.count
    if hasattr(metafunc.function, 'repeat'):
        mark = metafunc.function.repeat
        if len(mark.args) > 0 and isinstance(mark.args[0], int):
            count = metafunc.function.repeat.args[0]
    if count > 1:
        def make_progress_id(i, n=count):
            return '{0}/{1}'.format(i + 1, n)
        metafunc.parametrize(
            '__pytest_repeat_step_number',
            range(count),
            indirect=True,
            ids=make_progress_id,
        )
    """
    if metafunc.config.option.selective_test_file:
        with open(metafunc.config.option.selective_test_file, 'r') as f:
            content = f.readlines()
            module_name = [x.split('::')[0] for x in content]
            selected_nodeids = [x.rsplit('::', 1)[-1] for x in content]
            module_name = [os.path.relpath(x, str(metafunc.config.rootdir)) for x in module_name]
            #sequence = list(zip(module_name, selected_nodeids))
            #selected_nodeids = ['::'.join(tup) for tup in sequence]
            # remove whitespace characters like `\n` at the end of each line
            selected_nodeids = [x.rstrip('\n') for x in selected_nodeids]
            nodeid_count_dict = {}
            for nodeid in selected_nodeids:
                temp_lst = nodeid.split(',')
                if len(temp_lst) == 2:
                    nodeid_count_dict[temp_lst[0]] = int(temp_lst[1])

        def make_progress_id(i, n):
            return '{0}/{1}'.format(i + 1, n)

        metafunc.fixturenames.append('tmp_ct')
        if nodeid_count_dict:
            if metafunc.function.__name__ in nodeid_count_dict:
                def make_progress_id(i, n=nodeid_count_dict[metafunc.function.__name__]):
                    return '{0}of{1}'.format(i + 1, n)
                metafunc.parametrize('tmp_ct',range(nodeid_count_dict[metafunc.function.__name__]), ids=make_progress_id)
            else:
                print("{0} not found in {1}".format(metafunc.function.__name__,nodeid_count_dict ))
        metafunc.fixturenames.remove('tmp_ct')

def get_testcase_name(name):
    report_name = name.replace("::()::", ".")
    report_tokens = report_name.split('::')
    if len(report_tokens) > 1:
        report_name = "{klass}.{test}".format(klass=report_tokens[-2],test=report_tokens[-1])
    else:
        report_name = test=report_tokens[-1]
    return report_name

def pytest_collection_modifyitems(session, config, items):
    log = CafyLog("cafy")
    if config.option.selective_test_file:
        with open(config.option.selective_test_file, 'r') as f:
            content = f.readlines()
            content = [x.split(',')[0] for x in content]
            module_name =  [x.split('::')[0] for x in content]
            selected_nodeids = [x.split('::',1)[-1] for x in content]
            if items and not items[0].nodeid.startswith("::"):
                module_name = [os.path.relpath(x, str(config.rootdir)) for x in module_name]
                sequence = list(zip(module_name, selected_nodeids ))
                selected_nodeids = ['::'.join(tup) for tup in sequence]
                nodeid_pattern = re.compile(r'((?:[\w-]+\/)*[\w-]+\.[\w-]*\:\:[\w-]+\:?\:?\(?\)?\:?\:?[\w-]*)(\[[\w-]+\])?')
            else:
                selected_nodeids = ['::'+ x for x in selected_nodeids]
                nodeid_pattern = re.compile(r'(\:\:[\w-]+\:?\:?\(?\)?\:?\:?[\w-]*)(\[[\w-]+\])?')
            selected_nodeids = [x.rstrip('\n') for x in selected_nodeids]
        #Modify the items list by picking only those whose nodeid exists in selected_nodeids
        try:
            items[:] = [item for item in items if nodeid_pattern.match(item.nodeid).group(1) in selected_nodeids]
        except:
            log.debug("selected_nodeids = ", selected_nodeids)
            log.error("Error while picking selective testcases")
    if items:
        CafyLog.first_test = items[0]
    else:
        CafyLog.first_test = None
        log.info("****** No testcases are selected to execute ******")
    if config.option.enable_live_update:
        log.info("Live logging the status of testcases enabled.")
        os.environ['enable_live_update'] = 'True'
        #Send the registration_id to CAFY_API_HOST for live logging
        CAFY_API_HOST = os.environ.get('CAFY_API_HOST')
        CAFY_RUN_ID = os.environ.get('CAFY_RUN_ID')
        CAFY_API_KEY = os.environ.get('CAFY_API_KEY')
        log.info("CAFY_API_HOST:{0}, CAFY_RUN_ID:{1},  CAFY_API_KEY:{2}".format(CAFY_API_HOST, CAFY_RUN_ID, CAFY_API_KEY))
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Bearer {}'.format(os.environ.get('CAFY_API_KEY'))}
        try:
            if CafyLog.registration_id:
                url = '{0}/api/runs/{1}'.format(os.environ.get('CAFY_API_HOST'), os.environ.get('CAFY_RUN_ID'))
                log.info("url: {}".format(url))
                log.info("Calling API service for live logging of reg_id ")
                params = {"reg_id": CafyLog.registration_id}
                response = requests.patch(url, json=params, headers=headers, timeout=120)
                if response.status_code == 200:
                    log.info("Calling API service for live logging of reg_id successful")
                else:
                    log.warning("Calling API service for live logging of reg_id failed")
            else:
                log.warning("registration_id is not set, therefore not sending it to API service for live logging")
        except Exception as e:
            log.warning("Error while sending the reg_id to live logging's api server: {}".format(e))

        #Send the TestCases and its status(upcoming) collected to http://cafy3-dev-lnx:3100 for live logging
        try:
            for item in items:
                if not item.get_closest_marker('Future'):  #Exclude the Future marked testcases to be shown as upcoming
                    nodeid = item.nodeid.split('::()::')
                    finer_nodeid = nodeid[0].split('::')
                    class_name = finer_nodeid[-1]
                    d = dict()
                    d["case_name"] = '.'.join([class_name, item.name]) # To get the testcase_name in format of className.functionName as per allure xml
                    d["case_name"] = get_testcase_name(item.nodeid)
                    d["status"] = "upcoming"
                    CafyLog.collected_testcases.append(d)
            url = '{0}/api/runs/{1}/cases'.format(os.environ.get('CAFY_API_HOST'), os.environ.get('CAFY_RUN_ID'))
            log.debug("url: {}".format(url))
            log.debug("Calling API service for live logging of collected testcases ")
            response = requests.post(url, json=CafyLog.collected_testcases, headers=headers, timeout=120)
            if response.status_code == 200:
                log.info("Calling API service for live logging of collected testcases successful")
            else:
                log.warning("Calling API service for live logging of collected testcases failed")

        except Exception as e:
            log.warning("Error while sending the live status of testcases collected: {}".format(e))

def get_datentime():
    '''return date and time as string'''
    _time = time.time()
    return datetime.fromtimestamp(_time).strftime('%Y%m%d-%H%M%S')

def _setup_archive_env():
    '''setup archive env'''
    #print ('setting up env: ARCHIVE_DIR ')
    # create archive folder with 777 permision
    if not os.path.exists(CafyLog.work_dir):
        os.makedirs(CafyLog.work_dir, 0o777)
    else:
        pass
        #print ('{} is already created'.format(CafyLog.work_dir))
    # setup environment variable for cafy user to add files in archive
    os.environ['ARCHIVE_DIR'] = CafyLog.work_dir

def _setup_env():
    '''setup environment'''
    _setup_archive_env()

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Connection timed out.")

class EmailReport(object):

    '''
    Email report
    '''
    USER = getpass.getuser()
    CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
    CAFY_REPO = os.getenv("CAFY_REPO", None)
    # CAFY_REPO will be used for all cafy related logics
    START = datetime.now()
    START_TIME = time.asctime(time.localtime(START.timestamp()))

    def __init__(self, email_addr_list, email_from, email_from_passwd,
                 smtp_server, smtp_port, no_email, no_detail_message, topo_file, script_list, reg_dict, collection_list, cafypdb):
        '''
        @param email_addr_list: list of email address to which email needs to
        be sent.
        @param email_from: email address with which the email will be sent
        @param email_from_passwd: password of email_from email id
        @param smtp_server: smtp server
        @param smtp_port: smtp_port
        @param no_email: if True no email will be sent
        @param script_list: list of script/dir under execution which is
                            (option.file_or_dir)
        @type email_addr_list:  list
        @type email_from: str
        @type email_from_passwd: str
        @type smtp_server: str
        @type smtp_port: int
        @type no_email: bool
        @type script_listL list
        @param reg_dict : registration_dict for debug containing testbed file, input file,
                            debug file and reg_id
        '''
        self.email_addr_list = email_addr_list
        self.email_from = email_from
        self.email_from_passwd = email_from_passwd
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.no_email = no_email
        self.no_detail_message = no_detail_message
        self.script_list = script_list
        self.topo_file = topo_file
        self.reg_dict = reg_dict
        self.log = CafyLog("cafy")
        self.rclog = CafyLog("debug-rc")
        self.errored_testcase_count = {}
        self.analyzer_testcase = {}
        self.tabulate_html = None
        self.allure_html_report = None
        # using the first item of the script list for archive name as in most
        # cases it would be list with one element because we usally run pyest
        # with single test script
        _current_time = get_datentime()
        email_report = 'email_report.html'
        if self.CAFY_REPO:
            #self.archive_name = CafyLog.work_dir + '.zip'
            #self.archive = os.path.join(CafyLog.work_dir, self.archive_name)
            self.archive = CafyLog.work_dir
            self.email_report = os.path.join(CafyLog.work_dir,
                                             email_report)
        else:
            self.work_dir = None
            self.archive_name = None
            self.archive = None
            self.email_report = email_report

        # Testcase name and its status dict
        self.testcase_dict = OrderedDict()
        self.testcase_time = defaultdict(
            lambda : {'start_time': None, 'end_time': None})
        self.testcase_failtrace_dict = OrderedDict()
        #dict to have testcase as key and reproting status as value
        self.hybrid_mode_status_dict={}
        #list to find mode such as cli,ydk,oc
        self.mode_list=['cli','ydk','oc']
        self.report_dump={}
        self.temp_json={}
        self.model_coverage_report={}
        self.collection_manager = None
        self.collection_report = {'model_coverage':None,'collector_lsan':None,'collector_asan':None,'collector_yang':None}
        self.collection = collection_list
        self.debug_collector = False
        self.cafypdb = cafypdb
        self.debugger_quit = False
        self.cafypdb_user_action = ''

    def _sendemail(self):
        print("\nSending Summary Email to %s" % self.email_addr_list)
        msg = MIMEMultipart()
        # fixme: add exception handling
        with open(self.email_report) as email_fd:
            # create a text/plain message
            part = MIMEText(email_fd.read(), 'html')
            part['Content-Disposition'] = "inline"
            msg.attach(part)
        script_names = list()
        for script in self.script_list:
            script_names.append(script.split('/')[-1].replace(".py",""))
        msg['Subject'] = ("Cafy Report %s" % str(script_names)[2:-2])
        # changing the email_from from cafy-infra@cisco.com to nobody@cisco.com
        self.email_from = "%s@%s" % ("nobody", "cisco.com")
        msg['From'] = self.email_from
        mail_to = COMMASPACE.join(self.email_addr_list)
        msg['To'] = mail_to
        msg.add_header('Content-Type', 'text/html')
        # fixme: add an option to read config from file rather then CLI
        with smtplib.SMTP(self.smtp_server, self.smtp_port,timeout=60) as mail_server:
            if self.email_from_passwd:
                mail_server.ehlo()
                mail_server.starttls()
                mail_server.ehlo()
                mail_server.login(self.email_from, self.email_from_passwd)
            mail_server.send_message(msg)

    def _generate_with_template(self, terminalreporter):
        '''generate report using template'''
        #additional field of hybrid_mode_status_dict for html template in order display mode of each testcase in email report
        if hasattr(CafyLog,"hybrid_mode_dict") and CafyLog.hybrid_mode_dict.get('mode',None):
            cafy_kwargs = {'terminalreporter': terminalreporter,
                           'testcase_dict': self.testcase_dict,
                           'testcase_failtrace_dict':self.testcase_failtrace_dict,
                           'archive': self.archive,
                           'topo_file': self.topo_file,
                           'collection_report': self.collection_report,
                           'hybrid_mode_status_dict':self.hybrid_mode_status_dict}
        else:
            cafy_kwargs = {'terminalreporter': terminalreporter,
                           'testcase_dict': self.testcase_dict,
                           'testcase_failtrace_dict':self.testcase_failtrace_dict,
                           'archive': self.archive,
                           'topo_file': self.topo_file,
                           'collection_report': self.collection_report}
        report = CafyReportData(**cafy_kwargs)
        setattr(report,"tabulate_html", self.tabulate_html)
        template_file = os.path.join(self.CURRENT_DIR,
                                     "resources/mail_template.html")
        css_file = os.path.join(self.CURRENT_DIR,
                                "resources/cafy_report.css")
        with open(template_file) as html_src, open(css_file) as css_src:
            html_template = html_src.read()
            styles = css_src.read()
        template = Template(html_template)
        cafy_report_rendered = template.render(report=report,
                                               styles=styles)
        return cafy_report_rendered

    def _generate_email_report(self, terminalreporter):
        '''generate email report'''
        with open(self.email_report, 'w') as email_fd:
            email_fd.write(self._generate_with_template(terminalreporter))

    def _copy_files_to_archives(self, option):
        '''copy files to work archive folder'''
        # copy running script(s)/Directory
        file_or_dir_list = option.file_or_dir
        for file_or_dir in file_or_dir_list:
            src = file_or_dir
            if os.path.isdir(src):
                dst = os.path.join(CafyLog.work_dir, os.path.basename(src))
                shutil.copytree(src, dst)
            else:
                dst = CafyLog.work_dir
                shutil.copy2(src, dst)

    def _zip_it(self):
        '''zip everything under work_dir'''
        cwd = os.getcwd()
        os.chdir(CafyLog.work_dir)
        with zipfile.ZipFile(self.archive_name, 'w') as arc_zip:
            for file_or_dir in os.listdir(CafyLog.work_dir):
                if file_or_dir == self.archive_name:
                    continue
                else:
                    arc_zip.write(file_or_dir)
        os.chdir(cwd)

    def _create_archive(self, option):
        '''generate archive'''
        self._copy_files_to_archives(option)
        self._zip_it()
        print("Run archive is located at: %s" % CafyLog.work_dir)

    def get_test_name(self,name):
        report_name = name.replace("::()::", ".")
        report_tokens = report_name.split('::')
        if len(report_tokens) > 1:
            report_name = "{klass}.{test}".format(klass=report_tokens[-2],test=report_tokens[-1])
        else:
            report_name = test=report_tokens[-1]
        return report_name

    def get_open_files(self, pid):
        """
        Find files opened by specified process ID(s).
        Parameters
        ----------
        pids : list of int Process IDs.
        Returns
        -------
        files : list of str Open file names.
        """
        try:
            cmd = ['/usr/sbin/lsof', '-p', str(pid)]
            fd_out = subprocess.check_output(cmd)
            fd_out = str(fd_out).split("\\n")
            return fd_out
        except Exception:
            pass

    def get_open_files_of_pid_count(self, pid):
        """
        Find files opened by specified process ID(s).
        Parameters
        ----------
        pids :  Process IDs
        Returns: count
        """
        try:
            ps = subprocess.Popen(('lsof', '-p', str(pid)), stdout=subprocess.PIPE)
            fd_wc = subprocess.check_output(('wc'), stdin=ps.stdout)
            return str(fd_wc)
        except Exception:
            pass


    def update_cls_testcase(self, test_case):
        '''
        update cls with test case change update
        :param testcase:
        :return:
        '''
        try:
            url = "{0}/api/collector/{1}/case-update".format(cls_host, CafyLog.registration_id)
            params ={
                   "case_name" : test_case
            }
            self.log.info("Calling cls service (url:%s) for testcase" % test_case)
            response = _requests_retry(self.log, url, 'PUT', json=params, timeout=300)
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

    def initiate_analyzer(self, reg_id, test_case, debug_server):
        headers = {'content-type': 'application/json'}

        params = {"test_case": test_case,
                  "reg_id": reg_id,
                  "debug_server_name": debug_server}
        return register_object.initiate_analyzer(params=params,headers=headers)


    def pytest_runtest_setup(self, item):
        test_case = self.get_test_name(item.nodeid)
        self.log.set_testcase(test_case)
        if CLS and int(CLS) and CafyLog.registration_id:
            self.update_cls_testcase(test_case)
        if item == CafyLog.first_test and self.reg_dict:
            reg_id = self.reg_dict['reg_id']
            debug_server = CafyLog.debug_server
            self.initiate_analyzer(reg_id, test_case, debug_server)

    def pytest_runtest_teardown(self, item, nextitem):
        if nextitem is None:
            self.log.set_testcase("Teardown")
        else:
            testcase_name = self.get_test_name(nextitem.nodeid)
            self.log.set_testcase(testcase_name)
        testcase_name = self.get_test_name(item.nodeid)
        self.log.info('Teardown module for testcase {}'.format(testcase_name))

    @pytest.fixture(scope='function', autouse=True)
    def check_test_run(self, request):
        '''
        All the testcases will check if the CafyLog._triggerFlags list is non empty and if yes,
        check if the testcase is marked with a autofail marker that is present in the above list and if yes,
        raise an exception
        :param request:
        :return:
        '''
        marker = request.node.get_closest_marker('autofail')  # Is always None
        if not marker:
            return
        if bool(marker):
            for arg in marker.args:
                if request.node.parent.obj.has_autofail_trigger(arg):
                    raise CafyException.AutoFailMarkerException("Failing this testcase automatically as this has triggered condition %s from %s()" \
                                                                %(arg, CafyLog._triggerFlags[arg]))
                    #pytest.fail("Failing this testcase automatically as this has triggered condition %s" % arg)

    def post_testcase_status(self, reg_id, test_case, debug_server):
        analyzer_status = False
        headers = {'content-type': 'application/json'}
        params = {"test_case": test_case,
                  "reg_id": reg_id,
                  "debug_server_name": debug_server}
        analyzer_status = self.check_analyzer_status(params, headers)
        if not analyzer_status:
            self.log.info("Analyzer still working, Continuing Test case")
        return analyzer_status

    def check_analyzer_status(self, params, headers):
        result = register_object.analyzer_status(params=params,headers=headers)
        self.log.info(f'result of analyzer {result}')
        return result

    @pytest.hookimpl(trylast=True, hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        result = report.get_result()

        if call.when == "teardown":
            stdout_html = self._convert_to_html(result.capstdout)
            try:
                all_log_groupings = self._parse_all_log(result.capstdout.split('\n'))
                template_file_name = os.path.join(self.CURRENT_DIR,
                                        "resources/all_log_template.html")
                with open(template_file_name) as html_src:
                    html_template = html_src.read()
                    template = Template(html_template)
                stdout_html = template.render(log_groupings = all_log_groupings)
            except Exception as e:
                self.log.warning("Error while adding html filters to test_log {}".format(e))
            finally:
                allure.attach(stdout_html, 'test_log','text/html')

        if call.when == "call" and Cafy.RunInfo.active_exceptions:
            try:
                elist = list()
                #title = Cafy.RunInfo.active_exceptions.pop()
                for exception in Cafy.RunInfo.active_exceptions:
                    elist.append(exception)
                Cafy.RunInfo.active_exceptions = list()
                raise CafyException.CompositeError(elist)
            except:
                exc_info = sys.exc_info()
                einfo = _pytest._code.code.ExceptionInfo.from_current()
                call.excinfo = einfo
                repr = einfo.getrepr(style="line")
                result = report.get_result()
                report.exc_info = exc_info
                result.outcome = "failed"
                result.longrepr = repr
                report.force_result(result)

    def _convert_to_html(self, contents):
        """
        Converts log to HTML format. Adds different colors based on log prefix
        """
        ansi_escape = re.compile(r'\x1b[^m]*m')

        result = "<html><head><style>div { white-space: pre; }</style></head>"
        result += "<body style=\"font-family:'Courier New', Courier, monospace;font-size:14px\">"
        for raw_line in contents.splitlines():
            line = ansi_escape.sub('', raw_line)
            if line.startswith('-Warning'):
                result += "<div style=\"color:orange;\">"
            elif line.startswith('-Fail'):
                result += "<div style=\"color:black;background-color:red;font-weight:bold\">"
            elif line.startswith('-Error'):
                result += "<div style=\"color:red;font-weight:bold\">"
            elif line.startswith('-Liberr'):
                result += "<div style=\"color:red;font-weight:bold\">"
            elif line.startswith('-Success'):
                result += "<div style=\"color:black;background-color:green;\">"
            elif line.startswith('-Debug'):
                result += "<div style=\"color:pink\">"
            else:
                result += "<div>"
            result += html.escape(line)
            result += "</div>"
        result += "</body></html>"
        return result
    """
    method:get_final_status
    1. apply anding logic over the mode_list
       and return the anding value of all modes
    2. ex: if all mode =ydk then anding mode =ydk
       if all mode =cli then anding mode=cli
       if all mode=oc the anding mode=oc
       if mode list =['ydk','cli'] then anding mode='cli'
       if mode list=['oc','cli','cli'] the anding mode='cli'
    """
    def get_final_status(self,mode_list):
        final_mode=""
        if(len(mode_list)>0):
            if 'cli' in mode_list:
                return 'cli'
            else:
                final_mode=mode_list[0]
                for mode in mode_list:
                    final_mode=final_mode and mode
                return final_mode
        return final_mode

    """
    method:get_status
    1. take input as mode result of qualname on method
    2. running_mode var hold split value of mode by dot
    3. loop over mode_list if mode equal to running_mode then
       status value will be ydk,cli,or oc
    4. else if flag is false and method landed to Base class
       then status will be based on mode provided by user
    """
    def get_status(self,mode):
        try:
            running_mode=mode.split('.')[0].lower()
            for _mode in self.mode_list:
                if running_mode.endswith(_mode):
                    return _mode
            status = ''
            if hasattr(CafyLog,"hybrid_mode_dict") and CafyLog.hybrid_mode_dict.get('mode',None)=='oc':
                status = 'oc'
            elif hasattr(CafyLog,"hybrid_mode_dict") and  CafyLog.hybrid_mode_dict.get('mode',None)=='cli':
                status = 'cli'
            elif hasattr(CafyLog,"hybrid_mode_dict") and  CafyLog.hybrid_mode_dict.get('mode',None)=='ydk':
                status = 'ydk'
            elif hasattr(CafyLog,"hybrid_mode_dict") and  CafyLog.hybrid_mode_dict.get('mode',None)=='hybrid_ydk':
                status = 'ydk'
            elif hasattr(CafyLog,"hybrid_mode_dict") and  CafyLog.hybrid_mode_dict.get('mode',None)=='hybrid_oc':
                status = 'oc'
            return status
        except Exception as e:
            return e
    """
    method:get_mode
    1. take input as method_list returned by get_method
    2. loop over method_list for each method call qualname and get_status method
       which return mode like ydk,cli,or oc based on running mode of method and
       append the mode to mode_list
    3. return the mode_list for final mode determination
    """
    def get_mode(self,method_list):
        mode_list=[]
        for method in method_list:
            try:
                mode=method.__qualname__
                mode_list.append(self.get_status(mode))
            except Exception as e:
                mode_list.append(e)
        return mode_list

    """
    method:get_method
    1. loop over all functions of feature_lib inherited class stored in cafylog hybrid_mode_dict
    2. on each testcase running when any function from feature_lib class invoked for execution
       then its has_been_called attribute which seted dyanimically using decorator in meta class
       will seted to True and its detected when flag is True
    3. if has_been_called attribute is True append it to method list else continue
    4. after appending detected method to method_list make the has_been_called False
    5. return method_list for determination of modes of each method in method_list
    """
    def get_method(self):
        method_list=[]
        if hasattr(CafyLog,"hybrid_mode_dict") and CafyLog.hybrid_mode_dict.get('cls'):
            for cls in CafyLog.hybrid_mode_dict['cls']:
                for name, method in inspect.getmembers(cls, inspect.isfunction):
                    try:
                        if method.has_been_called==True and not name.startswith("__") and not name.startswith("_"):
                            method.has_been_called=False
                            method_list.append(method)
                    except Exception as e:
                        continue
        return method_list

    """
    Method: generate_collection_config
       Take collection_config_list and generate
       collection_config json
    """
    def generate_collection_config(self,collection_config_list):
        collection_config = {'debug': {'enabled': False}, 'lsan': {'enabled': False}, 'asan':{'enabled': False},'yang': {'enabled': False}}
        for config_key in collection_config_list:
            if config_key in collection_config:
                collection_config[config_key]['enabled'] = True
        path=CafyLog.work_dir
        file_name='collection_config.json'
        with open(os.path.join(path, file_name), 'w') as fp:
            json.dump(collection_config,fp)

    """
    Method: enable_collection
       enable_collection is a pytest fixture function which run in the starting of the setup of
       testcases at the module level
    if --collection args passed along with pytest cmd
       eg: --collection = ['lsan','debug','asan','yang','collection-config']
    then
       1: Generate collection config based on the pytest args passed by user
       2: get the topology file
       3: call collection setup by passing topology file and collection config list
       4: collection_setup.setup return collection_manager object which can be used for
          4.1: collection_manager connect
          4.2: collection_manager configure
          4.3: collection_manager dconfigure
          4.4:  collection_manager disconnect
    """
    @pytest.fixture(scope='module', autouse=True)
    def enable_collection(self, request):
        try:
            if self.collection:
                topo_file = CafyLog.topology_file
                self.generate_collection_config(self.collection)
                collection_config_file = os.path.join(CafyLog.work_dir, 'collection_config.json')
                self.collection_manager = collection_setup.setup(topo_file,collection_config_file)
                self.collection_manager.configure()
        except Exception as e:
            self.log.error("Collection Failed")

    pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report):
        testcase_name =  self.get_test_name(report.nodeid)
        if report.when == 'setup':
            self.log.set_testcase(testcase_name)
            self.log.title("Start test:  %s" %(testcase_name))
            register_object.register_testcase(testcase_name=testcase_name)

        if report.when == 'teardown':
            if self.reg_dict:
                reg_id = self.reg_dict.get('reg_id')
                test_class = report.nodeid.split('::')[1]
                if (test_class not in self.analyzer_testcase.keys()) or self.analyzer_testcase.get(test_class) == 1:
                    analyzer_status = self.post_testcase_status(reg_id, testcase_name, CafyLog.debug_server)
                    self.log.info('Analyzer Status is {}'.format(analyzer_status))
                else:
                    self.log.info('Analyzer is not invoked as testcase failed in setup')
            status = "unknown"
            if testcase_name in self.testcase_dict:
                # if error occur during module teardown then marking status as failed and adding stack_exception
                if report.longrepr:
                    status = 'failed'
                    self.temp_json["stack_exception"] = str(report.longrepr)
                    self.testcase_dict[testcase_name].status = 'failed'
                else:
                    status = self.testcase_dict[testcase_name].status
            try:
                if status != "passed" :
                    self.temp_json["name"] = testcase_name
                    self.temp_json['testcase_status'] = status
                    self.temp_json['error'] = CafyLog.fail_log_msg
                    self.temp_json["exception"] = self.log.exception_details
                    self.log.buffer_to_retest.append(self.temp_json)
                    self.temp_json={}
            except Exception as err:
                self.log.info("Error {} happened while getting deta for retest" .format(err))

            create_fd_file = os.environ.get('enable_fd_collection', False)
            if create_fd_file:
                self.log.info("File descriptor collection enabled and it will be saved in file_descriptors.txt in the archive")
                pid = os.getpid()
                fd_count = self.get_open_files_of_pid_count(pid)

                fd_list = self.get_open_files(pid)
                try:
                    with open(os.path.join(os.path.sep, CafyLog.work_dir, "file_descriptors.txt"), "a") as f:
                        f.write("\n")
                        f.write("Testcase_name : " +CafyLog.testcase_name)
                        f.write("\n")
                        if fd_count:
                            f.write("Count : %s" %fd_count)
                        f.write("\n")
                        f.write("_ _ _ _ _ "*15)
                        f.write("\n")
                        if fd_list:
                            for line in fd_list:
                                f.write(line + '\n')
                        f.write("\n")
                        f.write("==========" * 15)
                except Exception:
                    pass

            if os.environ.get('enable_live_update'):
                # Send the testcasename and its status along with failtrace if any to the live logging API service
                headers = {'Content-Type': 'application/json',
                                   'Authorization': 'Bearer {}'.format(os.environ.get('CAFY_API_KEY'))}
                try:
                    for item in CafyLog.collected_testcases:
                        if testcase_name in item.values():
                            item['status'] = self.testcase_dict[testcase_name].status
                            item['fail_log'] = self.testcase_dict[testcase_name].text_message
                            if testcase_name in self.testcase_failtrace_dict:
                                item['fail_log'] = CafyLog.fail_log_msg
                    url = '{0}/api/runs/{1}/cases'.format(os.environ.get('CAFY_API_HOST'),
                                                                 os.environ.get('CAFY_RUN_ID'))
                    # self.log.debug("url: {}".format(url))
                    # self.log.debug("Calling API service for live logging of executed testcases ")
                    # self.log.debug("JSON = {0}".format(json.dumps(CafyLog.collected_testcases, indent=4, sort_keys=True)))
                    response = requests.post(url, json=CafyLog.collected_testcases, headers=headers)
                    if response.status_code == 200:
                        self.log.info("Calling API service for live logging of executed testcase successful")
                    else:
                        self.log.warning("Calling API service for live logging of executed testcases failed")

                except Exception as e:
                    self.log.warning("Error while sending the live status of executed testcases: {}".format(e))
            """
            1. method:get_method gives output list of methods (one or more than one) presents per testcase
            2. method:get_mode take input of list of methods and gives output as mode such as cli,ydk or oc for each method as list of mode
            3. method:get_final_status take of list of mode and gives final reporting of testcase as ydk,cli or oc using anding logic on
               list of mode
            4. method_mode_dict will keep the info of all methods and mode in which it runned, fianl status, ydk coverage , cli coverage
               and oc coverage as percentage in the form of dict and finally will be dump as json file in work_dir
            """
            method_mode_dict={}
            method_list=self.get_method()
            mode_list=self.get_mode(method_list)
            final_status=self.get_final_status(mode_list)
            self.hybrid_mode_status_dict[testcase_name]=final_status
            for item in range(len(method_list)):
                method = method_list[item]
                module = method.__module__
                if module not in method_mode_dict:
                    method_mode_dict[module] = {}
                method_mode_dict[module][method.__name__] = mode_list[item]
            self.report_dump[testcase_name]={}
            self.report_dump[testcase_name]['method_mode']=method_mode_dict
            self.report_dump[testcase_name]['final_status']=final_status
            if mode_list:
                self.report_dump[testcase_name]['ydk_percentage']= (mode_list.count('ydk')/len(mode_list))*100
                self.report_dump[testcase_name]['cli_percentage']= (mode_list.count('cli')/len(mode_list))*100
                self.report_dump[testcase_name]['oc_percentage']= (mode_list.count('oc')/len(mode_list))*100
            if hasattr(CafyLog,"model_tracker_dict"):
                self.model_coverage_report[testcase_name]=CafyLog.model_tracker_dict
                CafyLog.model_tracker_dict={}
            self.log.title("Finish test: %s (%s)" %(testcase_name,status))
            self.log.info("="*80)

        #The following if block is executed for @pytest.mark.xfail(run=False) and
        #@@pytest.mark.skip(..) markers because testcases marked with these
        #will never go into call stage
        if report.when == 'setup':
           testcase_name = self.get_test_name(report.nodeid)
           testcase_status = report.outcome
           self.testcase_dict[testcase_name] = Cafy.TestcaseStatus(testcase_name,testcase_status,report.longrepr)
           if testcase_status == 'failed':
                if report.longrepr:
                    self.temp_json["stack_exception"] = str(report.longrepr)
                else:
                    self.temp_json["stack_exception"] = ""

        elif report.when == 'setup' and report.outcome == 'skipped':
            if hasattr(report, "wasxfail"):
                #This is to handle tests that are marked with @pytest.mark.xfail(run=False)
                #which means don't execute the testcase. Such testcase will never go into the
                #report.when=call stage
                testcase_name = self.get_test_name(report.nodeid)
                self.testcase_dict[testcase_name] = Cafy.TestcaseStatus(testcase_name,'xfailed',report.longrepr)

            else:
                #This is to handle tests that are marked with @pytest.mark.skip(..)
                #which means skip the testcase. Such testcase will never go into the
                #report.when=call stage
                testcase_name = self.get_test_name(report.nodeid)
                self.testcase_dict[testcase_name] = Cafy.TestcaseStatus(testcase_name,'skipped',report.longrepr)
            if report.longrepr:
                self.temp_json["stack_exception"]=str(report.longrepr)
            else:
                self.temp_json["stack_exception"]=""

        elif report.when == 'call':
            testcase_name = self.get_test_name(report.nodeid)
            if hasattr(report, "wasxfail"):
                if report.skipped:
                    testcase_status = "xfailed"
                elif report.passed:
                    testcase_status = "xpassed"
                else:
                    testcase_status = report.outcome

                self.testcase_dict[testcase_name] = Cafy.TestcaseStatus(testcase_name,testcase_status,report.longrepr)
                if testcase_status == 'failed':
                    self.testcase_failtrace_dict[testcase_name] = CafyLog.fail_log_msg
                    if report.longrepr:
                        self.temp_json["stack_exception"] = str(report.longrepr)
                    else:
                        self.temp_json["stack_exception"] = ""
            else:
                testcase_status = report.outcome
                self.testcase_dict[testcase_name] = Cafy.TestcaseStatus(testcase_name,testcase_status,report.longrepr)
                if testcase_status == 'failed':
                    if report.longrepr:
                        self.testcase_failtrace_dict[testcase_name] = report.longrepr
                        self.temp_json["stack_exception"]=str(report.longrepr)
                        self.log.error("stack_exception %s" %report.longrepr)
                    else:
                        self.testcase_failtrace_dict[testcase_name] = None
                else:
                    self.temp_json["stack_exception"]= ""
    

    def check_call_report(self, item, nextitem):
        """
        If test method in a testclass fails then mark the rest of the test methods
        in that as 'skipped'
        """
        reports = runtestprotocol(item, nextitem=nextitem)
        for report in reports:
            if report.when == "call":
                if report.outcome == "failed":
                    if 'insta-stop' in CafyLog.script_args:
                        #Get the list or value of insta-stop key passed to script-args
                        #on cmd line
                        insta_stop_methods = CafyLog.script_args['insta-stop']
                        #Get the class name of the method
                        class_name = item.cls
                        base_classes = inspect.getmro(class_name)
                        base_class_name = base_classes[0].__name__
                        #Make a string as class_name.method_name
                        method_with_class_name = base_class_name+'.'+item.name
                        if method_with_class_name in insta_stop_methods:
                            for test_method in item.parent._collected[item.parent._collected.index(item):]:
                                test_method.add_marker(pytest.mark.skipif("True"))
                break

    def pytest_runtest_protocol(self, item, nextitem):
        # add to the hook
        item.ihook.pytest_runtest_logstart(
            nodeid=item.nodeid, location=item.location,
        )
        self.check_call_report(item, nextitem)
        return True

    def send_email_for_remote_debugging(self,server_ip_address,available_port, run_id='local_run'):
        '''
        Method send_email_for_remote_debugging
        :param server_ip_address: server_ip_address
        :param available_port: available_port
        :param run_id: run_id , default=local_run for local runs
        :return: send server ip and port info as email notification
        '''
        self.log.info(f"Sending email notification for CafyPdb debugging connection for {run_id} to {self.email_addr_list}")
        msg = MIMEMultipart()
        doc_link = CafyPdb_Configs.get_cafypdb_doc()
        msg_body = f"""
                <html>
                <body>
                <p>CafyPdb remote debugging prompt for {run_id} is now available to connect remotely.</p>
                <p>Connection details: <br>
                Server_ip: {server_ip_address}, Port: {available_port} </p>
                <p>Use below telnet command to connect remotely: <br>
                telnet {server_ip_address} {available_port}</p>
                <p> Learn more about CafyPdb here: <a href={doc_link}>CafyPdb Documentation</a></p>
                </body>
                </html>
                """
        part = MIMEText(msg_body, 'html')
        part['Content-Disposition'] = "inline"
        msg.attach(part)
        msg['Subject'] = (f"CafyPdb remote debugging details for run_id: {run_id}")
        # changing the email_from from cafy-infra@cisco.com to nobody@cisco.com
        self.email_from = "%s@%s" % ("nobody", "cisco.com")
        msg['From'] = self.email_from
        mail_to = COMMASPACE.join(self.email_addr_list)
        msg['To'] = mail_to
        msg.add_header('Content-Type', 'text/html')
        # fixme: add an option to read config from file rather then CLI
        with smtplib.SMTP(self.smtp_server, self.smtp_port,timeout=60) as mail_server:
            if self.email_from_passwd:
                mail_server.ehlo()
                mail_server.starttls()
                mail_server.ehlo()
                mail_server.login(self.email_from, self.email_from_passwd)
            mail_server.send_message(msg)

    def send_webex_notification(self,server_ip_address,available_port, run_id='local_run'):
        '''
        Method: send_webex_notification
        :param server_ip_address: server_ip_address
        :param available_port: port
        :param run_id: run id
        :return: send notification to user for connection on webex
        '''
        try:
            USER = os.environ.get("CAFY_USER",getpass.getuser())
            API_KEY = CafyPdb_Configs.get_api_key()
            URL = CafyPdb_Configs.get_webex_url()
            doc_link = CafyPdb_Configs.get_cafypdb_doc()
            data = {
                "user_id":USER,
                "server_ip":server_ip_address,
                "port":available_port,
                "run_id":run_id,
                "doc_link":doc_link
                }
            data_json = json.dumps(data)
            headers = {'Content-Type': 'application/json',
                       'Authorization': 'Bearer {}'.format(API_KEY)}
            response = requests.post(URL, data=data_json, headers=headers)
            self.log.info(f"Cafy Debugger: Webex notification sent for remote debbugging connection:{response}")
        except Exception as e:
            self.log.info(f"Cafy Debugger:Failed to send webex notification:{e}")

    def send_notification(self,server_ip_address,available_port, run_id):
        '''
        Method: send_notification
        :param server_ip_address: server_ip_address
        :param available_port: port
        :return: send notification to user for connection on email and webex
        '''
        self.send_email_for_remote_debugging(server_ip_address,available_port, run_id)
        self.send_webex_notification(server_ip_address,available_port, run_id)

    def start_remote_connection(self,available_port):
        '''
        Method start_remote_connection
        :param: available_port
        :return: open remote connection
        '''
        run_id = os.environ.get("CAFY_RUN_ID", 'local_run')
        self.send_notification(self.server_ip_address,available_port,run_id)
        self.log.info(f"Cafy Debugger: Execution Server IP for Remote Pdb Connection: {self.server_ip_address}, and Available Port: {available_port}")
        #Handle time out if user do not connect in specified time in sec
        timeout = CafyPdb_Configs.get_connection_timeout()
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        try:
            self.remote_debugger = CafyPdb('0.0.0.0', available_port, patch_stdstreams=True)
            signal.alarm(0)
        except TimeoutException:
            # if timeout exception occur the close the port and connection
            self.log.info(f"Cafy Debugger: Connection timed out")
            self.close_port(self.available_port)

    def start_remote_pdb(self):
        """
        Method start_remote_pdb
        :param arg: None
        :return: remote connection
        """
        try:
            self.server_ip_address = self.get_server_ip()
            self.available_port = self.find_available_port()
            self.start_remote_connection(self.available_port)
        except Exception as e:
            self.log.info(f"Cafy Debugger:Failed to bind the port:{e}")

    def get_server_ip(self):
        """
        Method get server ip
        :param arg: None
        :return:  Find and return ip address of execution server
        """
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        return ip_address

    def find_available_port(self):
        """
        Method find_available_port
        :param arg: None
        :return:  Find and return an available port on the local machine from user defined range
        """
        start_port = 49152
        end_port = 65535
        # Iterate over the range of port numbers and try to bind the socket to each port
        available_port = None
        for port in range(start_port, end_port):
            try:
                # Create a TCP socket and bind it to the current port
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Set socket options to reuse the address
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                # Bind the socket to the port
                self.sock.bind(('0.0.0.0', port))
                available_port = self.sock.getsockname()[1]
                break
            except OSError:
                # Port is already in use, try the next one
                pass
        if available_port == None:
            return None
        return available_port

    def close_port(self,port):
        '''
        Method close_port
        :param port: port number
        :return: close the port
        '''
        try:
            self.sock.close()
            self.log.info(f"Cafy Debugger: {port} port closed - used for Cafy Debugging")
        except Exception as e:
            self.log.info("Cafy Debugger: closing port Failed {}".format(e))

    def pytest_exception_interact(self, node, call, report):
        '''
        if cafypdb enabled using --cafypdb then on exception or error init Custom pdb class
        custom pdb class CafyPdb
           1: override the default pdb into custom cafypdb
           2: get execution server ip and port
           3: invoke Remote connection for cafypdb (Remote Debugging)
        '''
        if self.cafypdb:
            try:
                testcase_name = self.get_test_name(report.nodeid)
                self.cafypdb_user_action = self.cafypdb_user_action +  "***********************************************************\n"+f"{testcase_name} : Cafy Debugger Session Started\n"
                #Start the Remote pdb connection using execution server ip and available user port
                if self.debugger_quit == False:
                    self.start_remote_pdb()
                    if hasattr(self, 'remote_debugger'):
                        self.log.info("Cafy Debugger: RemotePdb Connection Established")
                        #Get the traceback object from the excinfo attribute of the call object
                        exc_tb = call.excinfo.tb
                        self.remote_debugger.patch_stdstreams = True
                        #Start the CafyPdb Debugger
                        self.remote_debugger.post_mortem(exc_tb)
                        self.cafypdb_user_action = self.cafypdb_user_action +  f"{self.remote_debugger.user_action}"
                        pdb_exit_commands = ['q','quit','exit']
                        if self.remote_debugger.lastcmd in pdb_exit_commands:
                            self.log.info("Cafy Debugger: RemotePdb Session Ended by user")
                            self.debugger_quit = True
                        self.cafypdb_user_action = self.cafypdb_user_action +  f"{testcase_name} : Cafy Debugger Session Ended\n" + "***********************************************************" + "\n\n"
            except Exception as e:
                self.log.info("Cafy Debugger: Promt Failed {}".format(e))
            finally:
                self.close_port(self.available_port)

        if report.failed:
            CafyLog().fail(str(call.excinfo))
            if report.outcome == 'failed':
                #If config.debug_enable is False, the reg_dict is empty, So u want to skip talking to collector server
                if self.reg_dict:
                    if hasattr(report, 'when'):
                        if report.when == 'setup':
                            test_class = node.nodeid.split('::')[1]
                            if test_class not in self.analyzer_testcase.keys():
                                self.analyzer_testcase.update({test_class: 1})
                            else:
                                self.analyzer_testcase[test_class] += 1
                            if node.cls not in self.errored_testcase_count:
                                self.errored_testcase_count[node.cls] = 1
                            else:
                                self.errored_testcase_count[node.cls]+=1

                        if (node.cls in self.errored_testcase_count and self.errored_testcase_count[node.cls]==1) or report.when!='setup':
                            testcase_name = node.name
                            inherited_classes = []
                            if node.cls:
                                class_name = node.cls
                                base_classes = inspect.getmro(class_name)
                                for base_class in base_classes:
                                    if base_class.__name__ not in ["ApBase", "object"]:
                                        inherited_classes.append(base_class.__name__)
                                index = 1
                                if len(base_classes) == 3:
                                    index = 0
                                base_class_name = base_classes[index].__name__


                                #base_class_name = base_classes[1].__name__
                            else:
                                base_class_name = None
                            if "reg_id" in self.reg_dict:
                                reg_id = self.reg_dict["reg_id"]
                            else:
                                reg_id = '00'

                            exception_type = call.excinfo.type
                            try:
                                if issubclass(exception_type, CafyException.CafyBaseException):
                                    exception_details = call.excinfo.value.get_exception_details()
                                    self.log.exception_details = exception_details
                            except:
                                self.log.info("Error happened while getting exception details for retest")

                            # Check if the exception encountered is not an instance of CafyBaseException, then don't invoke collector service
                            if not issubclass(exception_type, CafyException.CafyBaseException):
                                self.log.info(
                                    "The encountered exception '%s' is not an instance of CafyBaseException, It could be a python built-in exception."
                                    " Therefore collector service will not be invoked " \
                                    % exception_type.__name__)

                            else:
                                collector_exception_name_list = []
                                collector_actual_obj_dict_list = []
                                collector_actual_obj_name_list = []
                                collector_failed_attribute_list = []
                                rc_exception_name_list = []
                                rc_actual_obj_dict_list = []
                                rc_actual_obj_name_list = []
                                rc_failed_attribute_list = []

                                exception_name = exception_type.__name__
                                if exception_name == "CompositeError":
                                    for curr_exception in call.excinfo.value.exceptions:
                                        exception_type = type(curr_exception).__name__
                                        call_dict = {}
                                        if 'VerificationError' in exception_type:
                                            exception_name = 'VerificationError'
                                            if hasattr(curr_exception, 'verifier'):
                                                call_dict['verifier'] = curr_exception.verifier
                                            if hasattr(curr_exception, 'columns'):
                                                call_dict['columns'] = curr_exception.columns
                                        elif 'TgenCheckTrafficError'in exception_type:
                                            exception_name = 'TgenCheckTrafficError'
                                            if hasattr(curr_exception, 'item_stats'):
                                                call_dict['item_stats'] = curr_exception.item_stats
                                            if hasattr(curr_exception, 'flow_stats'):
                                                call_dict['flow_stats'] = curr_exception.flow_stats
                                        else:
                                            exception_name = 'None'

                                        self.handle_all_exceptions(base_class_name, call_dict, exception_name,
                                                                   collector_exception_name_list, collector_actual_obj_dict_list,
                                                                   collector_actual_obj_name_list, collector_failed_attribute_list,
                                                                   rc_exception_name_list, rc_actual_obj_dict_list,
                                                                   rc_actual_obj_name_list,
                                                                   rc_failed_attribute_list)
                                else:
                                    call_dict = call.excinfo.value.__dict__
                                    self.handle_all_exceptions(base_class_name, call_dict, exception_name,
                                                               collector_exception_name_list, collector_actual_obj_dict_list,
                                                               collector_actual_obj_name_list, collector_failed_attribute_list,
                                                               rc_exception_name_list, rc_actual_obj_dict_list,
                                                               rc_actual_obj_name_list,
                                                               rc_failed_attribute_list)

                                headers = {'content-type': 'application/json'}

                                if len(collector_actual_obj_dict_list) > 0:
                                    params = {"testcase_name": testcase_name, "class_name": base_class_name,
                                              "inherited_classes": inherited_classes,
                                              "reg_dict": self.reg_dict, "actual_obj_name": collector_actual_obj_name_list,
                                              "actual_obj_dict": collector_actual_obj_dict_list,
                                              "failed_attr": collector_failed_attribute_list,
                                              "debug_server_name": CafyLog.debug_server,
                                              "exception_name": collector_exception_name_list}
                                    if report.when == 'setup':
                                        if hasattr(node.parent, 'cls') and self.debug_collector == False:
                                            self.debug_collector = True
                                            response = self.invoke_reg_on_failed_testcase(params, headers)
                                            if response is not None and response.status_code == 200:
                                               if response.text:
                                                   self.log.info("Setup: Debug Collector logs: %s" % response.text)
                                    elif report.when == 'call':
                                        response = self.invoke_reg_on_failed_testcase(params, headers)
                                        if response is not None and response.status_code == 200:
                                            if response.text:
                                                self.log.info("Test: Debug Collector logs: %s" % response.text)
                                    elif report.when == 'teardown':
                                        response = self.invoke_reg_on_failed_testcase(params, headers)
                                        if response is not None and response.status_code == 200:
                                            if response.text:
                                                self.log.info("Teardown: Debug Collector logs: %s" % response.text)


                                if len(rc_actual_obj_dict_list) > 0:
                                    params = {"testcase_name": testcase_name, "class_name": base_class_name,
                                              "inherited_classes": inherited_classes,
                                              "reg_dict": self.reg_dict, "actual_obj_name": rc_actual_obj_name_list,
                                              "actual_obj_dict": rc_actual_obj_dict_list, "failed_attr": rc_failed_attribute_list,
                                              "debug_server_name": CafyLog.debug_server,
                                              "exception_name": rc_exception_name_list}
                                    response = self.invoke_rc_on_failed_testcase(params, headers)
                                    if response is not None and response.status_code == 200:
                                        if response.json().get("traffic_logs"):
                                            self.rclog.info("Debug RC logs: \n%s" % response.json()["traffic_logs"])
                    else:
                        self.log.debug("Type of report obtained is %s. Debug engine is only triggered for reports of type TestReport" %type(report))

    def handle_all_exceptions(self, base_class_name, call_dict, exception_name,
                              collector_exception_name_list,
                              collector_actual_obj_dict_list,
                              collector_actual_obj_name_list,
                              collector_failed_attribute_list,
                              rc_exception_name_list,
                              rc_actual_obj_dict_list,
                              rc_actual_obj_name_list,
                              rc_failed_attribute_list):
        failed_attr = []
        if (exception_name == "VerificationError") and \
                bool(call_dict):
            actual_obj_name = None
            actual_obj_dict = {}
            failed_attr = []
            if 'verifier' in call_dict:
                actual_obj = call_dict['verifier']
                actual_obj_name = actual_obj.__class__.__qualname__
                blacklist_keys = ['log',
                                  '__compared_to__']  # We dont want to pass these keys and thie values because they r not json serializable
                actual_obj_dict = {}
                for key, val in actual_obj.__dict__.items():
                    if key not in blacklist_keys and is_jsonable(val):
                        actual_obj_dict[key] = val
                    else:
                        self.log.info("json serializable issue in value for key %s" %key)
                if 'columns' in call_dict:
                    failed_attr = call_dict['columns']
                else:
                    self.log.error("'columns' key not found in %s" %call_dict)

                # Verification errors are sent to Collector, so add to
                # the collector list to be used for collection service
                collector_actual_obj_dict_list.append(actual_obj_dict)
                collector_actual_obj_name_list.append(actual_obj_name)
                collector_failed_attribute_list.append(failed_attr)
                collector_exception_name_list.append(exception_name)
            else:
                self.log.error("Verification Error encountered , but 'verifier' key not found in %s. "
                               "The absence of 'verifier' key could be due to this exception not being raised from "
                               "verification code. Therefore debug engine's collector  won't be invoked " % call_dict)


        elif (exception_name == "TgenCheckTrafficError") and \
                bool(call_dict):
            #item_stats and flow_stats keys are mandatory in TgenCheckTrafficError exception.
            # If not, it could be a misuse of exception like being raised without a context
            if 'item_stats' in call_dict:
                item_stats = call_dict['item_stats']
                if 'flow_stats' in call_dict:
                    flow_stats = call_dict['flow_stats']

                    failed_attr = ["traffic_error"]
                    actual_obj_dict = {"item_stats": item_stats, "flow_stats": flow_stats}
                    actual_obj_name = "traffic_stats"

                    # Traffic errors are sent to RC Engine, so add to
                    # the RC list to be used for RC Engine service
                    rc_actual_obj_dict_list.append(actual_obj_dict)
                    rc_actual_obj_name_list.append(actual_obj_name)
                    rc_failed_attribute_list.append(failed_attr)
                    rc_exception_name_list.append(exception_name)

                    collector_actual_obj_dict_list.append(None)
                    collector_actual_obj_name_list.append(None)
                    collector_failed_attribute_list.append(None)
                    collector_exception_name_list.append(exception_name)
                else:
                    self.log.error("'flow_stats' key not found in %s. "
                                   "Could be because TgenCheckTrafficError exception is not raised in the context " %call_dict)
            else:
                self.log.error("'item_stats' key not found in %s. "
                               "Could be because TgenCheckTrafficError exception is not raised in the context" % call_dict)

        else:
            # All other errors are sent to Collector, so add to
            # the collector list to be used for collection service
            collector_actual_obj_dict_list.append(None)
            collector_actual_obj_name_list.append(None)
            collector_failed_attribute_list.append(failed_attr)
            collector_exception_name_list.append(exception_name)


    def invoke_reg_on_failed_testcase(self, params, headers):
        """
        will call debug service api to start collection
        :param params: failure details of testcase for given run
        :param headers: headers associated with api request call
        """
        return register_object.collector_call(params=params, headers=headers)
    

    def invoke_rc_on_failed_testcase(self, params, headers):
        return register_object.rc_call(params=params, headers=headers)

    #method: To dump the mode report as testcase_mode.json file in work_dir
    def dump_hybrid_mode_report(self):
        path=CafyLog.work_dir
        file_name='testcase_mode.json'
        with open(os.path.join(path, file_name), 'w') as fp:
            json.dump(self.report_dump,fp)

    #method: To dump the model coverage report as model_coverage.json file in work_dir
    def dump_model_coverage_report(self):
       path=CafyLog.work_dir
       file_name='model_coverage.json'
       with open(os.path.join(path, file_name), 'w') as fp:
           json.dump(self.model_coverage_report,fp)

    #method: To collect the cafypdb user actions into a file in work_dir
    def cafypdb_log(self):
        path=CafyLog.work_dir
        file_name = "cafypdb.log"
        with open(os.path.join(path, file_name), 'w') as log_file:
            log_file.write(self.cafypdb_user_action)

    def collect_collection_report(self):
        path=CafyLog.work_dir
        if os.path.exists(os.path.join(path, 'model_coverage.json')):
            self.collection_report['model_coverage'] = os.path.join(path, 'model_coverage.json')
        if os.path.exists(os.path.join(path, 'lsan')):
            self.collection_report['collector_lsan'] = os.path.join(path, 'lsan')
        if os.path.exists(os.path.join(path, 'asan')):
            self.collection_report['collector_asan'] = os.path.join(path, 'asan')
        if os.path.exists(os.path.join(path, 'yang')):
            self.collection_report['collector_yang'] = os.path.join(path, 'yang')

    def pytest_terminal_summary(self, terminalreporter):
        '''this hook is the execution point of email plugin'''
        #self._generate_email_report(terminalreporter)
        self._generate_all_log_html()
        if self.CAFY_REPO:
            option = terminalreporter.config.option
            # self._create_archive(option)
            #If junitxml option is given on cmd line, this file is available
            #only after run is complete
            _junitxml_filename = os.environ.get('junitxml')
            if _junitxml_filename:
                junitxml_filename = os.path.basename(_junitxml_filename)
                junitxml_file_path = os.path.join(CafyLog.work_dir, junitxml_filename)
                #Chec if source and dest are same, then don't copy else copy
                if junitxml_file_path != _junitxml_filename:
                    copyfile(_junitxml_filename, junitxml_file_path)
                    os.chmod(junitxml_file_path, 0o775)

        # if mode present then print the reporting mode of per testcase as separate coloumn Testcase_mode else report same as ealier
        if hasattr(CafyLog,"hybrid_mode_dict") and CafyLog.hybrid_mode_dict.get('mode',None):
           terminalreporter.write_line("\n TestCase Summary Status Table")
           hybrid_mode_test_list = []
           hybrid_mode_dict=self.hybrid_mode_status_dict
           mode_status=""
           for k,v in self.testcase_dict.items():
               if v.name in hybrid_mode_dict.keys():
                  mode_status=hybrid_mode_dict[v.name]
               hybrid_mode_test_list.append([v.name, v.status,mode_status])
           headers = ['Testcase_name', 'Status','Testcase_mode']
           self.tabulate_result = tabulate(hybrid_mode_test_list, headers=headers[:], tablefmt='grid')
           terminalreporter.write_line(self.tabulate_result)
           self.dump_hybrid_mode_report()
        else:
           terminalreporter.write_line("\n TestCase Summary Status Table")
           temp_list = []

           for k,v in self.testcase_dict.items():
               try:
                   message = v.message.chain[0][1].message
               except:
                   message = v.message
               temp_list.append((v.name, v.status))
           headers = ['Testcase_name', 'Status']
           self.tabulate_result = tabulate(temp_list, headers=headers[:], tablefmt='grid')
           terminalreporter.write_line(self.tabulate_result)
        self.dump_model_coverage_report()
        terminalreporter.write_line("Results: {work_dir}".format(work_dir=CafyLog.work_dir))
        terminalreporter.write_line("Reports: {allure_html_report}".format(allure_html_report=self.allure_html_report))
        self.collect_collection_report()
        self.cafypdb_log()
        self._generate_email_report(terminalreporter)

        if not self.no_email:
            self._sendemail()

        #Unset environ variables cafykit_mongo_learn & cafykit_mongo_read if set
        if os.environ.get('cafykit_mongo_learn'):
            del os.environ['cafykit_mongo_learn']
        if os.environ.get('cafykit_mongo_read'):
            del os.environ['cafykit_mongo_read']



    def _parse_all_log(self, input_file_handler):
        log_parsing_state = LogState.NONE
        log_grouping = None
        separator_line = re.compile('-[a-zA-Z]+-+.*> [=]+$')
        start_test_line = re.compile('Start test:\W+(.*)$')
        end_test_line = re.compile('Finish test:\W+(.*)\W\((.*)\)$')
        split_log_line = re.compile('^-+([a-zA-Z]+)-+(.*)$')

        all_log_groupings = []
        for log_line in input_file_handler:
            escape_re = re.compile(r'\x1b\[[0-9;]*m')
            log_line = re.sub(escape_re, "", log_line)
            if separator_line.search(log_line):
                continue
            elif start_test_line.search(log_line):
                # When we encounter start of test case, irrespective of current state we reset to LogState.TESTCASE
                name = start_test_line.search(log_line).group(1)
                log_grouping = TestCase(name=name, description="")
                all_log_groupings.append(log_grouping)
                log_parsing_state = LogState.TESTCASE
            elif end_test_line.search(log_line):
                if log_parsing_state is LogState.TESTCASE:
                    if end_test_line.search(log_line).group(2) == 'failed':
                        log_grouping.failed = True
                    log_parsing_state = LogState.NONE
                else:
                    # raise ValueError('Cannot end a test case from this state')
                    pass
            else:
                if log_parsing_state is LogState.NONE:
                    # print("Starting generic log")
                    log_grouping = GenericLogGrouping()
                    all_log_groupings.append(log_grouping)
                    log_parsing_state = LogState.GENERIC
                processed_log_line = split_log_line.search(log_line)
                if processed_log_line:
                    log_grouping.append_log_line(LogLine(html.escape(processed_log_line.group(2)), processed_log_line.group(1).upper()))
                else:
                    log_grouping.append_log_line(LogLine(html.escape(log_line), 'OUT'))

        return all_log_groupings

    def _generate_all_log_html(self):
        log_file_name = os.path.join(CafyLog.work_dir, "all.log")
        try:
            input_file_handler = open(log_file_name, 'r')
            all_log_groupings = self._parse_all_log(input_file_handler)
            template_file_name = os.path.join(self.CURRENT_DIR,
                                     "resources/all_log_template.html")
            with open(template_file_name) as html_src:
                html_template = html_src.read()
                template = Template(html_template)
            output_file_name = os.path.join(CafyLog.work_dir, "all.log.html")
            with open(output_file_name, 'w') as output_file:
                output_file.write(template.render(log_groupings = all_log_groupings))
        except FileNotFoundError:
                return

    def _get_analyzer_log(self):
        register_object.analyzer_log(work_dir=CafyLog.work_dir)


    def _generate_allure_report(self):
        try:
            allure_path = "/auto/cafy/cafykit/allure2/latest/bin/allure"
            if not os.path.exists(allure_path):
                allure_path = "allure"
            allure_source_dir = os.path.join(self.archive,"allure")
            allure_report_dir = os.path.join(self.archive,"reports")
            cmd = "{allure_path} generate {allure_source_dir} --report-dir {allure_report_dir}".format(
                        allure_path=allure_path,
                        allure_source_dir=allure_source_dir,
                        allure_report_dir=allure_report_dir)
            #print("Allure Command Line Used: {cmd}".format(cmd=cmd))
            allure_report = os.path.join(allure_report_dir,"index.html")
            CafyLog.htmlfile_link = allure_report
            allure_html_report = os.path.join(_CafyConfig.allure_server,allure_report.strip("/"))
            self.allure_html_report = allure_html_report
            os.system(cmd)
            #print("Report Generated at: {allure_report}".format(allure_report=allure_report))
            self.log.info("Report: {allure_html_report}".format(allure_html_report=allure_html_report))
            _CafyConfig.summary["allure2"] = {
                    "commandline" : cmd,
                    "html" :  allure_html_report,
                    "source_dir": allure_source_dir,
                    "report_dir": allure_report_dir,
                    "report": allure_report,
                }
        except Exception as e:
            self.log.error("Error in generating allure report: {}".format(e))


    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self):
        test_data_file = os.path.join(CafyLog.work_dir, "testdata.json")
        _CafyConfig.summary["test_data"] = {
            "location": test_data_file
        }
        self.log.info("Test data generated at %s" % test_data_file)
        CafyLog.TestData.save(test_data_file,overwrite=True)
        debug_enabled_status = os.getenv("cafykit_debug_enable", None)

        self._generate_allure_report()

        if debug_enabled_status and CafyLog.registration_id:
            self.log.title("End run for registration id: %s" % CafyLog.registration_id)
            self._get_analyzer_log()
            params = {"reg_id": CafyLog.registration_id,
                      "topo_file": CafyLog.topology_file,
                      "input_file": CafyLog.test_input_file}
            headers = {'content-type': 'application/json'}
            register_object.collector_log(params=params, headers=headers, work_dir=CafyLog.work_dir)

        try:
            with open(os.path.join(CafyLog.work_dir, "retest_data.json"), "w") as f:
                f.write(json.dumps(self.log.buffer_to_retest, indent=4))
        except Exception as error:
            self.log.info(error)
        summary_file = os.path.join(self.archive,"summary.json")
        with open(summary_file, 'w') as outfile:
            json.dump(_CafyConfig.summary, outfile, indent=4, sort_keys=True)

        if self.collection:
            self.collection_manager.deconfigure()

class CafyReportData(object):

    '''cafy email report class'''

    build_info = namedtuple('build_info', ['XR_Workspace', 'XR_EFR',
                                           'Calvados_Workspace',
                                           'Calvados_EFR'])
    testcase = namedtuple('testcase', ['name', 'result', 'fail_log', 'url'])
    summary = namedtuple('summary', ['passed', 'failed', 'not_run', 'total'])

    def __init__(self, terminalreporter, testcase_dict, testcase_failtrace_dict, archive, topo_file, hybrid_mode_status_dict=None, collection_report=None):
        self.terminalreporter = terminalreporter
        self.testcase_dict = testcase_dict
        self.testcase_failtrace_dict = testcase_failtrace_dict
        self.hybrid_mode_status_dict=hybrid_mode_status_dict
        self.collection_report_dict = collection_report
        self.start = EmailReport.START
        self.start_time = EmailReport.START_TIME
        # Basic details
        option = self.terminalreporter.config.option
        self.script_list = option.file_or_dir
        self.title = ' '.join(self.script_list)
        self.image = os.getenv("IMAGE", "Unknown")
        if os.environ.get("BUILD_URL"):
            self.jenkins_url = os.environ.get("BUILD_URL") + "console"
        else:
            self.jenkins_url = None
        # Build Info
        self.xr_ws = os.getenv("XRWS", "Unknown")
        self.xr_efr = os.getenv("XREFR", "Unknown")
        self.cal_ws = os.getenv("CALWS", "Unknown")
        self.cal_efr = os.getenv("CALEFR", "Unknown")
        self.build_info = CafyReportData.build_info(self.xr_ws,
                                                    self.xr_efr,
                                                    self.cal_ws,
                                                    self.cal_efr)
        self.debug_dir = os.getenv("DEBUG_DIR", "Unknown")

        # Time
        self.pc_start = os.environ.get("PC_START")
        self.pc_stop = os.environ.get("PC_STOP")
        elapsed = datetime.now() - self.start
        self.stop_time = time.asctime(time.localtime(time.time()))
        self.run_time = self.get_readable_time(elapsed)

        # Run Info
        self.exec_host = platform.node()
        self.python_version = platform.python_version()
        self.platform = platform.platform()
        try:
            self.cafykit_release = os.path.basename(os.environ.get("VIRTUAL_ENV"))
        except:
            self.cafykit_release = None

        self.testbed = None
        self.registration_id = CafyLog.registration_id
        self.submitter = EmailReport.USER
        self.cafy_repo = EmailReport.CAFY_REPO
        self.topo_file = topo_file
        self.run_dir = self.terminalreporter.startdir.strpath
        try:
            self.git_commit_id = subprocess.check_output(['git', 'rev-parse', 'origin/main'], timeout=5, stderr=subprocess.DEVNULL).decode("utf-8").replace('\n', '')
        except Exception:
            self.git_commit_id = None
        self.archive = CafyLog.work_dir
        # summary result
        status_lists = {
            'passed': [],
            'failed': [],
            'skipped': [],
            'xpassed': [],
            'xfailed': []
        }
        for v in self.testcase_dict.values():
            if v.status in status_lists:
                status_lists[v.status].append(v.status)
        self.passed = len(status_lists['passed'])
        self.failed = len(status_lists['failed'])
        self.skipped = len(status_lists['skipped'])
        self.xpassed = len(status_lists['xpassed'])
        self.xfailed = len(status_lists['xfailed'])
        self.total = self.passed + self.failed + self.skipped + self.xpassed + self.xfailed
        if self.terminalreporter.config.option.mail_if_fail is True and self.total == self.passed and self.total != 0:
            self.terminalreporter.config._email.no_email = True

        # testcase summary result
        self.testcase_name = testcase_dict.keys()
        if CafyLog.htmlfile_link:
            self.allure_report = CafyLog.htmlfile_link
            if CafyLog.web_host:
                self.htmlprefix = CafyLog.web_host
            else:
                if self.allure_report.startswith(('/ws', '/auto')):
                    self.htmlprefix = 'http://allure.cisco.com'
                else:
                    self.htmlprefix = 'file:///'
        else:
            self.allure_report = None

        email_html_filename = 'email_report.html'
        path = self.cafy_repo
        file_link = os.path.join(
            os.path.sep, self.archive, email_html_filename)
        if os.path.isfile(file_link):
            if CafyLog.web_host:
                html_link = os.path.join(
                        os.path.sep, CafyLog.web_host, file_link)
            else:
                if path.startswith(('/auto', '/ws')):
                    html_link = os.path.join(
                            os.path.sep, 'http://allure.cisco.com', file_link)
                else:
                    html_link = os.path.join(
                            os.path.sep, 'file:///', file_link)
            CafyLog.email_htmlfile_link = file_link
        else:
            print('\n Email html report not generated')





        if CafyLog.email_htmlfile_link:
            self.summary_report = CafyLog.email_htmlfile_link
            if CafyLog.web_host:
                self.htmlprefix = CafyLog.web_host
            else:
                if self.summary_report.startswith(('/ws', '/auto')):
                    self.htmlprefix = 'http://allure.cisco.com'
                else:
                    self.htmlprefix = 'file:///'
        else:
            self.summary_report = None



    @staticmethod
    def get_readable_time(delta):
        """
        Convert time object into a human-readable format
        """
        _m, _s = divmod(delta.seconds, 60)
        _h, _m = divmod(_m, 60)
        _d = delta.days
        if _d > 0:
            run_time = "{}d {}h".format(_d, _h)
        elif _h > 0:
            run_time = "{}h {}m".format(_h, _m)
        elif _m > 0:
            run_time = "{}m {}s".format(_m, _s)
        else:
            run_time = "{}s".format(_s)
        return run_time


class LogGrouping:
    def get_subgroupings(self):
        return []

    def get_title(self):
        pass

    def get_log_lines(self):
        pass

    def append_log_line(self, line):
        pass


class LogLine:
    def __init__(self, line, type = None):
        self.line = line
        self.type = type

class GenericLogGrouping(LogGrouping):
    def __init__(self):
        self.log_lines = []

    def get_title(self):
        if len(self.log_lines) > 0:
            return self.log_lines[0].line[0:80] + "... and " + str(len(self.log_lines)) + " more lines"
        else:
            return "Generic log line"

    def get_log_lines(self):
        return self.log_lines

    def append_log_line(self, line):
        self.log_lines.append(line)


class TestCase(LogGrouping):
    def __init__(self, name=None, description=None):
        self.name = name
        self.description = description
        self.log_lines = []
        self.failed = False

    def get_title(self):
        return 'Test case: ' + self.name + (' ***Failed***' if self.failed else '')

    def get_log_lines(self):
        return self.log_lines

    def append_log_line(self, line):
        self.log_lines.append(line)

class LogState(Enum):
    NONE = 1
    GENERIC = 2
    TESTCASE = 3
    STEP = 3
