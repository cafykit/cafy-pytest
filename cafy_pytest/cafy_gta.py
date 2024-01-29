import time
import pytest
from logger.cafylog import CafyLog
import os
import inspect
from jinja2 import Template

class TimeCollectorPlugin:
    def __init__(self):
        self.original_sleep = time.sleep
        self.granular_time_testcase_dict = dict()
        self.test_case_name = None
        self.start_time = None
        self.total_execution_time = None
        self.original_set_methods = {}

    def measure_time_for_set_methods(self, method):
        """
        Measure the time taken by set methods.
        This method wraps set methods to measure their execution time.
        param method (function): The set method to be measured.
        Returns: function: The wrapped method.
        """
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
                if 'set_command' not in self.granular_time_testcase_dict[current_test]:
                    self.granular_time_testcase_dict[current_test]['set_command'] = dict()
                if method_name not in self.granular_time_testcase_dict[current_test]['set_command']:
                    self.granular_time_testcase_dict[current_test]['set_command'][method_name] = []
                self.granular_time_testcase_dict[current_test]['set_command'][method_name].append(float(elapsed_time))
            elif method_name.startswith('get'):
                if 'get_command' not in self.granular_time_testcase_dict[current_test]:
                    self.granular_time_testcase_dict[current_test]['get_command'] = dict()
                if method_name not in self.granular_time_testcase_dict[current_test]['get_command']:
                    self.granular_time_testcase_dict[current_test]['get_command'][method_name] = []
                self.granular_time_testcase_dict[current_test]['get_command'][method_name].append(float(elapsed_time))
            return result

        return wrapper

    def measure_sleep_time(self, duration):
        '''
        Method measure_sleep_time : it will measure the actual time taken by testcase method during sleep
        param duration: duration or sleep time declared in TC fucntion's
        return : Update the graunular time at test case level
        '''
        start_time = time.perf_counter()
        self.original_sleep(duration)
        end_time = time.perf_counter()
        elapsed_time = '%.2f' % (end_time - start_time)
        self.update_granular_time("sleep_time", elapsed_time)

    def patch_set_methods_for_test_instance(self, item):
        """
        Perform setup and teardown actions for test cases.
        This method performs setup and teardown actions for test cases,including monkey patching sleep and set methods.
        param request: The test request.
        Yields: None
        """
        test_case_class = item.cls
        if test_case_class:
            # Get the module of the test case class
            module = inspect.getmodule(test_case_class)
            for class_name, class_obj in inspect.getmembers(module, inspect.isclass):
                # Iterate over the attributes of the class
                for method_name, method in inspect.getmembers(class_obj, inspect.isfunction):
                    # Check if the attribute is callable and its name starts with 'set'
                    if callable(method) and method_name.startswith('set') or method_name.startswith('get') :
                        original_method = getattr(class_obj, method_name)
                        setattr(class_obj, method_name, self.measure_time_for_set_methods(original_method))

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, request):
        '''
        Method setup_and_teardown : it will Monkey patch the sleep time, set level command and get level command etc
        param request: take request
        '''
        self.start_time = time.perf_counter()
        # Monkey patch time.sleep
        time.sleep = self.measure_sleep_time
        # Monkey patch 'set' methods for all classes in the module
        self.patch_set_methods_for_test_instance(request.node)
        yield  # This is where the test case runs
        self.pytest_runtest_teardown(request.node, None)

    def pytest_runtest_protocol(self, item, nextitem):
        '''
        Method pytest_runtest_protocol : it will Monkey patch sleep , subprocess run etc
        Monkey patching used for modifying the behavior of built-in classes or functions, or adding instrumentation or logging to existing code.
        param item : test case item
        param  nextitem : test case nextitem
        return : None
        '''
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

    def update_granular_time(self, category, elapsed_time, command = None):
        '''
        Method update_granular_time : it will update the time at test case level
        param category : category like bash time, sleep time etc.
        param  elapsed_time : time spend during event like sleep, bash etc
        return : Update the graunular time at test case level
        '''
        current_test = self.test_case_name
        if current_test not in self.granular_time_testcase_dict:
            self.granular_time_testcase_dict[current_test] = dict()

        if category not in self.granular_time_testcase_dict[current_test]:
            self.granular_time_testcase_dict[current_test][category] = dict()
            if category == "sleep_time":
                self.granular_time_testcase_dict[current_test][category]["sleep_time"] = list()
                self.granular_time_testcase_dict[current_test][category]["sleep_time"].append(float(elapsed_time))
            elif category == "set_command" and command:
                self.granular_time_testcase_dict[current_test][category] = dict()
                self.granular_time_testcase_dict[current_test][category][str(command)] = float(elapsed_time)
            elif category == "get_command" and command:
                self.granular_time_testcase_dict[current_test][category] = dict()
                self.granular_time_testcase_dict[current_test][category][str(command)] = float(elapsed_time)

        else:
            if category == "sleep_time":
                    self.granular_time_testcase_dict[current_test][category]["sleep_time"].append(float(elapsed_time))
            elif category == "set_command" and command:
                if str(command) not in self.granular_time_testcase_dict[current_test][category]:
                    self.granular_time_testcase_dict[current_test][category][str(command)] = float(elapsed_time)
            elif category == "get_command" and command:
                if str(command) not in self.granular_time_testcase_dict[current_test][category]:
                    self.granular_time_testcase_dict[current_test][category][str(command)] = float(elapsed_time)

    def pytest_runtest_teardown(self, item, nextitem):
        end_time = time.perf_counter()
        self.total_execution_time = '%.2f' % (end_time - self.start_time)
        current_test = self.test_case_name
        self.granular_time_testcase_dict[current_test]["total_execution_time"] = self.total_execution_time
        self.total_execution_time = None

    def collect_granular_time_accouting_report(self):
        '''
        Method collect_granular_time_accouting_report : it will create report and save in cafy work dir
        return : create report for time accounting in cafy work dir as granular_time_report.json
        '''
        time_report = dict()
        for test_case, times in self.granular_time_testcase_dict.items():
            time_report[test_case] = dict()
            if 'sleep_time' in times:
                time_report[test_case]['sleep_time'] = times["sleep_time"]
            else:
                time_report[test_case]['sleep_time'] =  []
            if 'set_command' in times:
                time_report[test_case]['set_command'] = times['set_command']
            else:
                time_report[test_case]['set_command'] = {}
            if 'get_command' in times:
                time_report[test_case]['get_command'] = times['get_command']
            else:
                time_report[test_case]['get_command'] = {}
            time_report[test_case]['total_execution_time'] =  times["total_execution_time"]
        self.granular_time_testcase_dict = time_report

    def pytest_terminal_summary(self, terminalreporter):
        '''
        Method pytest_terminal_summary : terminal reporting 
        return : None
        '''
        self.collect_granular_time_accouting_report()
        # Create a Jinja2 environment and load the HTML template
        CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
        template_file = os.path.join(CURRENT_DIR,"resources/gta_template.html")
        with open(template_file) as html_src:
            html_template = html_src.read()
        template = Template(html_template)
        html_content = template.render(dictionary_data=self.granular_time_testcase_dict)
        # Define the path to the output HTML file
        path=CafyLog.work_dir
        html_file_path = os.path.join(path, 'granular_time_report.html')
        # Write the HTML content to the output file
        with open(html_file_path, 'w') as html_file:
            html_file.write(html_content)
