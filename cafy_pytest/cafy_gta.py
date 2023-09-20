import time
import builtins
import subprocess
import pytest
from logger.cafylog import CafyLog
import json
import os
import inspect
from jinja2 import Template

class TimeCollectorPlugin:
    def __init__(self):
        self.original_sleep = time.sleep
        self.original_subprocess_run = subprocess.run
        self.granular_time_testcase_dict = dict()
        self.test_case_name = None
        self.start_time = None
        self.total_execution_time = None

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

    def measure_subprocess_run(self, *args, **kwargs):
        '''
        Method measure_subprocess_run : it will measure the actual time taken by testcase function during executing subprocess run
        param args : args
        param kwargs : kwargs
        return : Update the graunular time at test case level
        '''
        start_time = time.perf_counter()
        # Capture the command
        command = args[0] if args else None
        process = self.original_subprocess_run(*args, **kwargs)
        end_time = time.perf_counter()
        elapsed_time = '%.2f' % (end_time - start_time)
        self.update_granular_time("bash_time", elapsed_time, command)

    def patch_subprocess(self):
        '''
        Method patch_subprocess : it will Monkey patch subprocess gfor bash commands.
        Monkey patching used for modifying the behavior of built-in classes or functions, or adding instrumentation or logging to existing code.
        param item : test case item
        param  nextitem : test case nextitem
        return : None
        '''
        # Monkey patch subprocess.run
        subprocess.run = self.measure_subprocess_run

    def unpatch_subprocess(self):
        '''
        Method unpatch_subprocess : it will Restore the original subprocess functions
        '''
        # Restore the original subprocess functions
        subprocess.run = self.original_subprocess_run

    def pytest_runtest_protocol(self, item, nextitem):
        '''
        Method pytest_runtest_protocol : it will Monkey patch sleep , subprocess run etc
        Monkey patching used for modifying the behavior of built-in classes or functions, or adding instrumentation or logging to existing code.
        param item : test case item
        param  nextitem : test case nextitem
        return : None
        '''
        self.start_time = time.perf_counter()
        # Monkey patch time.sleep
        time.sleep = self.measure_sleep_time

        #Monkey patch subprocess
        self.patch_subprocess()

        #get class name of test case method
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
                self.granular_time_testcase_dict[current_test][category]["total_sleep_time"] = float(elapsed_time)
            elif category == "bash_time" and command:
                self.granular_time_testcase_dict[current_test][category][str(command)] = elapsed_time
        else:
            if category == "sleep_time":
                    self.granular_time_testcase_dict[current_test][category]["total_sleep_time"] += float(elapsed_time)
            elif category == "bash_time" and command:
                if str(command) not in self.granular_time_testcase_dict[current_test][category]:
                    self.granular_time_testcase_dict[current_test][category][str(command)] = elapsed_time

    def pytest_runtest_teardown(self, item, nextitem):
        '''
        Method pytest_runtest_call : will measure Total execution time of test case method
        return : Update the graunular time at test case level
        '''
        end_time = time.perf_counter()
        self.total_execution_time ='%.2f' % (end_time - self.start_time)
        current_test = self.test_case_name
        self.granular_time_testcase_dict[current_test]["total_time"] = self.total_execution_time
        self.total_execution_time = None

    def collect_granular_time_accouting_report(self):
        '''
        Method collect_granular_time_accouting_report : it will create report and save in cafy work dir
        return : create report for time accounting in cafy work dir as granular_time_report.json
        '''
        time_report = dict()
        for test_case, times in self.granular_time_testcase_dict.items():
            sleep_time = times.get("sleep_time", 0)
            total_time = times.get("total_time",0)
            bash_time = times.get("bash_time",0)
            time_report[test_case] = dict()
            time_report[test_case]['Sleep time'] = sleep_time
            time_report[test_case]['Bash time'] = bash_time
            time_report[test_case]['Exec Time'] = None
            time_report[test_case]['Config Time'] = None
            time_report[test_case]['Get level command Time'] = None
            time_report[test_case]['Set level command Time'] = None
            time_report[test_case]['Inter Commands Delay Time'] = None
            time_report[test_case]['Total Execution Time'] = total_time
        self.granular_time_testcase_dict = time_report


    def cleanup(self):
        # Restore the original subprocess functions when done
        self.unpatch_subprocess()

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
        self.cleanup()
