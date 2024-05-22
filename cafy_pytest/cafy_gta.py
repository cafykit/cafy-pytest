import time
from logger.cafylog import CafyLog
import os
import inspect
import functools
import inspect
import requests
import json
from .cafygta_config import CafyGTA_Configs

class TimeCollectorPlugin:
    def __init__(self):
        self.original_sleep = time.sleep
        self.granular_time_testcase_dict = dict()
        self.test_case_name = None
        self.total_sleep_time = 0
        self.total_set_command_time = 0
        self.total_get_command_time = 0
        self.command_list = ['set_command','get_command','sleep_time']

    def update_granular_time_testcase_dict(self, current_test, event, method_name, elapsed_time, feature_type):
        """
        granular_time_testcase_dict
        param current_test: current_test
        param event: command like set , get or time.sleep
        param method_name: method name
        param elapsed_time: total time for each command ie, set or get
        param feature_type: infra or non-infra
        """
        if current_test not in self.granular_time_testcase_dict:
            self.granular_time_testcase_dict[current_test] = dict()
        if event not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test][event] = dict()
        if method_name not in self.granular_time_testcase_dict[current_test][event]:
            self.granular_time_testcase_dict[current_test][event][method_name] = list()
        self.granular_time_testcase_dict[current_test][event][method_name].append([float(elapsed_time),feature_type])
    
    def get_method_type(self,method):
        '''
        method get_method_type
        param method : method 
        '''
        file_path = method.__code__.co_filename
        feature_type = None
        if file_path:
            feature_type = "non-infra" if "lib/feature_lib" in file_path or "lib/hw" in file_path else "infra"
        return feature_type

    def measure_time_for_set_or_get_methods(self, method, cls_name):
        """
        Measure the time taken by set methods.
        This method wraps set methods to measure their execution time.
        param method (function): The set method to be measured.
        Returns: function: The wrapped method.
        """
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = method(*args, **kwargs)
            end_time = time.perf_counter()
            elapsed_time_seconds = end_time - start_time
            elapsed_time_microseconds = elapsed_time_seconds * 1000000
            elapsed_time = '%.2f' % (elapsed_time_microseconds)
            # Update granular time at the test case level
            current_test = self.test_case_name
            if current_test not in self.granular_time_testcase_dict:
                self.granular_time_testcase_dict[current_test] = dict()
            method_name = method.__name__
            feature_type = self.get_method_type(method)
            if method_name.startswith('set'):
                self.update_granular_time_testcase_dict(current_test,'set_command', ".".join([cls_name, method.__name__]), elapsed_time, feature_type)
            elif method_name.startswith('get'):
                self.update_granular_time_testcase_dict(current_test, 'get_command', ".".join([cls_name, method.__name__]), elapsed_time, feature_type)
            return result
        return wrapper

    def measure_sleep_time(self, duration):
        '''
        Method measure_sleep_time : it will measure the actual time taken by testcase method during sleep
        param duration: duration or sleep time declared in TC fucntion's
        return : Update the graunular time at test case level
        '''
        caller_frame = inspect.currentframe().f_back
        caller_method_name = caller_frame.f_code.co_name
        caller_class = caller_frame.f_locals.get('self').__class__
        # Get the method of the caller's class
        if caller_class is not None:
            caller_method = getattr(caller_class, caller_method_name, None)
            if caller_method is not None:
                current_test = self.test_case_name
                start_time = time.perf_counter()
                self.original_sleep(duration)
                end_time = time.perf_counter()
                elapsed_time_seconds = end_time - start_time
                elapsed_time_microseconds = elapsed_time_seconds * 1000000
                elapsed_time = '%.2f' % (elapsed_time_microseconds)
                feature_type = self.get_method_type(caller_method)
                self.update_granular_time_testcase_dict(current_test, "sleep_time", ".".join([caller_class.__name__, caller_method.__name__,"time.sleep"]), elapsed_time, feature_type)

    def patch_set_or_get_methods_for_test_instance(self, item):
        """
        Perform setup and teardown actions for test cases.
        This method performs setup and teardown actions for test cases,including monkey patching sleep and set methods.
        param request: The test request.
        Yields: None
        """
        # To avoid maximum recursion depth error
        if getattr(item.cls, '_decorated', None):
            return
        test_case_class = item.cls
        if test_case_class:
            # Get the module of the test case class
            module = inspect.getmodule(test_case_class)
            for class_name, class_obj in inspect.getmembers(module, inspect.isclass):
                # Iterate over the attributes of the class
                for method_name, method in inspect.getmembers(class_obj, inspect.isfunction):
                    # Check if the attribute is callable and its name starts with 'set'
                    if callable(method) and method_name.startswith('set') or method_name.startswith('get') :
                        #skipping appyling timer on setup method of testclass
                        if method_name == 'setup_method':
                            continue
                        else:
                            original_method = getattr(class_obj, method_name)
                            setattr(class_obj, method_name, self.measure_time_for_set_or_get_methods(original_method,class_name))
        if item.cls is not None:
            setattr(item.cls, '_decorated', True)

    def pytest_runtest_protocol(self, item, nextitem):
        '''
        Method pytest_runtest_protocol : it will Monkey patch sleep , subprocess run etc
        Monkey patching used for modifying the behavior of built-in classes or functions, or adding instrumentation or logging to existing code.
        param item : test case item
        param  nextitem : test case nextitem
        return : None
        '''
        # Monkey patch time.sleep
        time.sleep = self.measure_sleep_time
        # Monkey patch 'set' methods for all classes in the module
        self.patch_set_or_get_methods_for_test_instance(item)
        # get class name of the test case method
        base_class_name = ""
        if item.cls:
            class_name = item.cls
            base_classes = inspect.getmro(class_name)
            base_class_name = base_classes[0].__name__
        if base_class_name:
            self.test_case_name = f"{base_class_name}.{item.name}"
        else:
            self.test_case_name = f"{item.name}"
        return None
    
    def update_gta_dict(self,current_test, command):
        '''
        update_gta_dict
        :param current_test: current_test
        :param command: command
        '''
        if command not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test][command] = dict()
        if hasattr(CafyLog,"gta_dict") and command in CafyLog.gta_dict:
            for key, value in CafyLog.gta_dict[command].items():
                self.granular_time_testcase_dict[current_test][command][key] = value
        
    def update_CafyLog_gta_dict(self, current_test):
        """
        Update the CafyLog Granular Time Accounting (GTA) dictionary with timing information for the current test
        :param current_test:The name of the current test being executed
        :return : none
        """
        if current_test not in self.granular_time_testcase_dict:
            self.granular_time_testcase_dict[current_test] = dict()
        for command in self.command_list:
            self.update_gta_dict(current_test,command)

    def pytest_runtest_teardown(self, item, nextitem):
        """
        Execute teardown actions after a test has been executed
        :param item: The test item that was executed
        :param nextitem: The next test item in the test suite
        :return: None
        """
        current_test = self.test_case_name
        self.update_CafyLog_gta_dict(current_test)
        CafyLog.gta_dict = {}

    def get_time_data(self,data, event):
        '''
        get time data
        this method will take the timings list for each sleep_time , set_command or get_command 
        and it will club into as sum and occurence
        param data : timings data
        '''
        tmp_dict = {}
        for command, timings_list in data.items():
            if isinstance(timings_list, list):
                total_sum = sum(sublist[0] for sublist in timings_list)
                length = len(timings_list)
                feature_type = timings_list[0][1]
                if event == 'sleep_time':
                    self.total_sleep_time = self.total_sleep_time + total_sum
                elif event == 'set_command':
                    self.total_set_command_time = self.total_set_command_time + total_sum
                elif event == 'get_command':
                    self.total_get_command_time = self.total_get_command_time + total_sum
                tmp_dict[command] = ["{:.2f}".format(total_sum), length, feature_type]
            else:
                tmp_dict[command] = timings_list
        return tmp_dict

    def collect_granular_time_accouting_report(self):
        '''
        Method collect_granular_time_accouting_report : it will create report and save in cafy work dir
        return : create report for time accounting in cafy work dir as granular_time_report.json
        '''
        time_report = dict()
        for test_case, events in self.granular_time_testcase_dict.items():
            time_report[test_case] = dict()
            if 'sleep_time' in events:
                time_report[test_case]['sleep_time'] = self.get_time_data(events["sleep_time"],'sleep_time')
            else:
                time_report[test_case]['sleep_time'] =  dict()
            if 'set_command' in events:
                time_report[test_case]['set_command'] = self.get_time_data(events["set_command"],'set_command')
            else:
                time_report[test_case]['set_command'] = dict()
            if 'get_command' in events:
                time_report[test_case]['get_command'] = self.get_time_data(events["get_command"],'get_command')
            else:
                time_report[test_case]['get_command'] = dict()

            time_report[test_case]['total_sleep_time'] = "{:.2f}".format(self.total_sleep_time)
            time_report[test_case]['total_set_command_time'] = "{:.2f}".format(self.total_set_command_time)
            time_report[test_case]['total_get_command_time'] = "{:.2f}".format(self.total_get_command_time)
            time_report[test_case]['total_time'] = "{:.2f}".format(self.total_sleep_time+self.total_set_command_time+self.total_get_command_time)
            self.total_sleep_time = 0
            self.total_set_command_time = 0
            self.total_get_command_time = 0
        return time_report
    
    def add_gta_data_into_db(self, time_report,run_id='local_run'):
        '''
        add_gta_data_into_db
        :param time_report: gta report json data
        '''
        try:
            URL = CafyGTA_Configs.get_gta_url()
            API_KEY = CafyGTA_Configs.get_api_key()
            data = dict()
            data['run_id'] = run_id
            data['gta'] = time_report
            data_json = json.dumps(data)
            headers = {'Content-Type': 'application/json',
                       'Authorization': 'Bearer {}'.format(API_KEY)}
            response = requests.post(URL, data=data_json, headers=headers)
            if response.status_code == 200:
                print('GTA data updated to Mongo db:', response.status_code)
            else:
                print('Failed to update GTA data to Mongo db, Status code:', response.status_code)
        except Exception as e:
            print(e)

    def get_tranformed_gta_data(self, gta):
        '''
        get_tranformed_gta_data
        :param gta : gta data
        '''
        transformed_gta = dict()
        for key, value in gta.items():
            transformed_gta[key] = {"categories": {}, "totals": {}}
            if value is not None:
                for category, data in value.items():
                    if category.startswith("total_"):
                        transformed_gta[key]["totals"][category] = float(data)
                    else:
                        transformed_gta[key]["categories"][category] = [
                            {
                                "source": method.replace(".", "."),
                                "total_time": float(values[0]),
                                "occurence": float(values[1]),
                                "type": values[2]
                            }
                            for method, values in data.items()
                        ]
        return transformed_gta

    def pytest_terminal_summary(self, terminalreporter):
        '''
        Method pytest_terminal_summary : terminal reporting 
        return : None
        '''
        time_report = self.collect_granular_time_accouting_report()
        gta_data = self.get_tranformed_gta_data(time_report)
        path=CafyLog.work_dir
        file_name='cafy_gta.json'
        with open(os.path.join(path, file_name), 'w') as fp:
            json.dump(gta_data,fp)
        #Update gta data into mongo db
        run_id = os.environ.get("CAFY_RUN_ID", 'local_run')
        self.add_gta_data_into_db(gta_data,run_id)