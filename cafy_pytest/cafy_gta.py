import time
import pytest
from logger.cafylog import CafyLog
import os
import inspect
from jinja2 import Template
import functools
import sys
import inspect

class TimeCollectorPlugin:
    def __init__(self):
        self.original_sleep = time.sleep
        self.granular_time_testcase_dict = dict()
        self.test_case_name = None
        self.total_sleep_time = 0
        self.total_set_command_time = 0
        self.total_get_command_time = 0

    def update_granular_time_testcase_dict(self, current_test, event, method_name, elapsed_time ):
        """
        granular_time_testcase_dict
        param current_test: current_test
        param event: command like set , get or time.sleep
        param method_name: method name
        param elapsed_time: total time for each command ie, set or get
        """
        if current_test not in self.granular_time_testcase_dict:
            self.granular_time_testcase_dict[current_test] = dict()
        if event not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test][event] = dict()
        if method_name not in self.granular_time_testcase_dict[current_test][event]:
            self.granular_time_testcase_dict[current_test][event][method_name] = []
        self.granular_time_testcase_dict[current_test][event][method_name].append(float(elapsed_time))

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
            elapsed_time = '%.2f' % (end_time - start_time)
            # Update granular time at the test case level
            current_test = self.test_case_name
            if current_test not in self.granular_time_testcase_dict:
                self.granular_time_testcase_dict[current_test] = dict()
            method_name = method.__name__
            if method_name.startswith('set'):
                self.update_granular_time_testcase_dict(current_test,'set_command', ".".join([cls_name, method.__name__]), elapsed_time)
            elif method_name.startswith('get'):
                self.update_granular_time_testcase_dict(current_test, 'get_command', ".".join([cls_name, method.__name__]), elapsed_time)
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
                elapsed_time = '%.2f' % (end_time - start_time)
                self.update_granular_time_testcase_dict(current_test, "sleep_time", ".".join([caller_class.__name__, caller_method.__name__,"time.sleep"]), elapsed_time)

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

    def update_CafyLog_gta_dict(self, current_test):
        """
        Update the CafyLog Granular Time Accounting (GTA) dictionary with timing information for the current test
        :param current_test:The name of the current test being executed
        :return : none
        """
        if current_test not in self.granular_time_testcase_dict:
            self.granular_time_testcase_dict[current_test] = dict()
        if 'set_command' not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test]['set_command'] = dict()
        if hasattr(CafyLog,"gta_dict") and 'set_command' in CafyLog.gta_dict:
            for key, value in CafyLog.gta_dict['set_command'].items():
                self.granular_time_testcase_dict[current_test]['set_command'][key] = value
        if 'get_command' not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test]['get_command'] = dict()
        if hasattr(CafyLog,"gta_dict") and 'get_command' in CafyLog.gta_dict:
            for key, value in CafyLog.gta_dict['get_command'].items():
                self.granular_time_testcase_dict[current_test]['get_command'][key] = value

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
                total_sum = sum(timings_list)
                length = len(timings_list)
                if event == 'sleep_time':
                    self.total_sleep_time = self.total_sleep_time + total_sum
                elif event == 'set_command':
                    self.total_set_command_time = self.total_set_command_time + total_sum
                elif event == 'get_command':
                    self.total_get_command_time = self.total_get_command_time + total_sum
                tmp_dict[command] = ["{:.2f}".format(total_sum), length]
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
                time_report[test_case]['sleep_time'] =  {}
            if 'set_command' in events:
                time_report[test_case]['set_command'] = self.get_time_data(events["set_command"],'set_command')
            else:
                time_report[test_case]['set_command'] = {}
            if 'get_command' in events:
                time_report[test_case]['get_command'] = self.get_time_data(events["get_command"],'get_command')
            else:
                time_report[test_case]['get_command'] = {}

            time_report[test_case]['total_sleep_time'] = "{:.2f}".format(self.total_sleep_time)
            time_report[test_case]['total_set_command_time'] = "{:.2f}".format(self.total_set_command_time)
            time_report[test_case]['total_get_command_time'] = "{:.2f}".format(self.total_get_command_time)
            time_report[test_case]['total_time'] = "{:.2f}".format(self.total_sleep_time+self.total_set_command_time+self.total_get_command_time)
            self.total_sleep_time = 0
            self.total_set_command_time = 0
            self.total_get_command_time = 0
        return time_report

    def pytest_terminal_summary(self, terminalreporter):
        '''
        Method pytest_terminal_summary : terminal reporting 
        return : None
        '''
        time_report = self.collect_granular_time_accouting_report()
        # Create a Jinja2 environment and load the HTML template
        CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
        template_file = os.path.join(CURRENT_DIR,"resources/gta_template.html")
        with open(template_file) as html_src:
            html_template = html_src.read()
        template = Template(html_template)
        html_content = template.render(dictionary_data=time_report)
        # Define the path to the output HTML file
        path=CafyLog.work_dir
        html_file_path = os.path.join(path, 'granular_time_report.html')
        # Write the HTML content to the output file
        with open(html_file_path, 'w') as html_file:
            html_file.write(html_content)
