import io
import os
import pdb
import re
import sys

from remote_pdb import RemotePdb

# Cafykit imports
from logger.cafylog import CafyLog
from topology.topo_mgr.topo_mgr import Topology


class OutputCapture:
    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self._stdout_orig = sys.stdout
        self._stderr_orig = sys.stderr

    def start_capture(self):
        sys.stdout = self._wrap_stream(sys.stdout, self.stdout)
        sys.stderr = self._wrap_stream(sys.stderr, self.stderr)

    def stop_capture(self):
        sys.stdout = self._stdout_orig
        sys.stderr = self._stderr_orig

    def get_captured_output(self):
        return self.stdout.getvalue() + self.stderr.getvalue()

    @staticmethod
    def _wrap_stream(stream, capture_buffer):
        class StreamWrapper:
            def __init__(self, stream, capture_buffer):
                self.stream = stream
                self.capture_buffer = capture_buffer
            def write(self, text):
                self.stream.write(text)
                self.capture_buffer.write(text)
        return StreamWrapper(stream, capture_buffer)

class CafyPdb(RemotePdb):
    def __init__(self, host, port,patch_stdstreams=True):
        super(CafyPdb, self).__init__(host, port,patch_stdstreams=patch_stdstreams)
        self.prompt = "(cafy-pdb)"
        self.topology_file = CafyLog.topology_file
        self.testbed_object = Topology(self.topology_file)
        self.custom_commands = {
            'Local': ['show_locals','feature_lib_locals'],
            'Router': ['show_routers', 'show_router_info'],
            'Device': ['show_devices', 'show_connected_devices']
        }
        self.patch_stdstreams = patch_stdstreams
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        self.user_action = ''

    def do_quit(self, arg):
        """
        Method quit
        :param arg: arg
        :return: Exit
        """
        # Call the parent class method to quit the debugger
        super().do_quit(arg)

    def postcmd(self, stop, line):
        self.user_action = self.user_action + f"> {line} command executed\n"
        if line == 'q' or line == 'quit' or line =='exit':
            self.output_capture.stop_capture()
        else:
            captured_output = self.output_capture.get_captured_output()
            if captured_output:
                self.user_action = self.user_action + f"Output of {line}:\n"
                self.user_action = self.user_action + f"  {captured_output}\n"
            self.output_capture = OutputCapture()
            self.output_capture.start_capture()
        return super().postcmd(stop, line)

    def post_mortem(self, traceback):
        pdb_exit_commands = ['q', 'quit', 'exit']
        if self.lastcmd in pdb_exit_commands:
            self.user_action = f"  * quit executed\n"
            return
        if self.patch_stdstreams and self.lastcmd not in pdb_exit_commands:
            sys.stdout = self.stdout
            sys.stderr = self.stderr
        # Reset the state of the debugger. It clears the list of breakpoints and sets the current frame
        self.reset()
        self.output_capture = OutputCapture()
        self.output_capture.start_capture()
        self.interaction(None, traceback)
        self.output_capture.stop_capture()

    def do_help(self, arg=None):
        """
        Method do helpp
        :param arg: argument
        :return: help
        """
        if arg:
            # If argument is provided, display the help for the specified command
            try:
                return pdb.Pdb.do_help(self, arg)
            except AttributeError:
                pass
        default_pdb = dir(CafyPdb)
        default_commands = [method[3:] for method in dir(default_pdb) if method.startswith("do_")]
        # Display the help for all custom commands in categories
        categories = self.custom_commands.keys()
        for category in categories:
            command_buffer = []
            for command in self.custom_commands[category]:
                command_buffer.append(command)
                if command in default_commands:
                    default_commands.remove(command)
            print(f"\n{category} commands (type help <topic>):")
            print("--------------------------------------------")
            for command in sorted(command_buffer):
                docstring = getattr(CafyPdb, "do_" + command).__doc__
                if docstring:
                    print(f"  {command:<15} {docstring.splitlines()[0]}")
                else:
                    print(f"  {command:<15}")

    def do_h(self,arg = None):
        """
        Method to provide help
        :param arg: None
        :return: None
        """
        self.do_help(arg)

    def help_show_routers(self):
        """
        Method help all router info
        :return: print help 
        """
        print("""
        This command will print out the routers.
        """)

    def do_show_routers(self,arg=None):
        """
        Method to print all router info
        :param arg: None
        :return: all router info
        """
        print("Routers Info")
        routers = []
        if hasattr(self.testbed_object,"get_routers"):
            router_dict = self.testbed_object.get_routers()
            for key, value in router_dict.items():
                routers.append(key)
        print(routers)

    def help_show_router_info(self):
        """
        Method help router info
        :return: print help
        """
        print("""
        This command require router name as arg and display the router info.
        """)

    def do_show_router_info(self,arg=None):
        """
        Method to print router info
        :param arg: None
        :return: router info
        """
        router_info = {
            'alias': None,
            'is_connected': None,
            'is_uut': None,
            'port': None,
            'pxe_info': None,
            'default_handles': [],
            'links': [],
            'tftp_server': None,
            'interfaces': [],
            'virtual': None,
            'skip_bake': None,
            'sim_config': None,
            'sim_dir': None,
            'sim_yaml_path': None,
            'image_version': None,
        }
        if arg:
            if hasattr(self.testbed_object,"get_routers"):
                router_dict = self.testbed_object.get_routers()
                if str(arg) in router_dict:
                    if hasattr(router_dict[str(arg)], 'alias'):
                        router_info['alias'] = router_dict[str(arg)].alias
                    if hasattr(router_dict[str(arg)], 'is_connected'):
                        router_info['is_connected'] = router_dict[str(arg)].is_connected()
                    if hasattr(router_dict[str(arg)], 'is_uut'):
                        router_info['is_uut'] = router_dict[str(arg)].is_uut
                    if hasattr(router_dict[str(arg)], 'virtual'):
                        router_info['virtual'] = router_dict[str(arg)].virtual
                    if hasattr(router_dict[str(arg)], 'skip_bake'):
                        router_info['skip_bake'] = router_dict[str(arg)].skip_bake
                    if hasattr(router_dict[str(arg)], 'port'):
                        router_info['port'] = router_dict[str(arg)].port
                    if hasattr(router_dict[str(arg)], 'pxe_info'):
                        router_info['pxe_info'] = router_dict[str(arg)].pxe_info
                    if hasattr(router_dict[str(arg)], 'default_handles'):
                        default_handles = router_dict[str(arg)].default_handles
                        for key, value in default_handles.items():
                            router_info['default_handles'].append(key)
                    if hasattr(router_dict[str(arg)], 'sim_yaml_path'):
                        router_info['sim_yaml_path'] = router_dict[str(arg)].sim_yaml_path
                    if hasattr(router_dict[str(arg)], 'sim_dir'):
                        router_info['sim_dir'] = router_dict[str(arg)].sim_dir
                    if hasattr(router_dict[str(arg)], 'sim_config'):
                        router_info['sim_config'] = router_dict[str(arg)].sim_config
                    if hasattr(router_dict[str(arg)], 'sim_config'):
                        router_info['sim_config'] = router_dict[str(arg)].sim_config
                    if hasattr(router_dict[str(arg)], 'image_version'):
                        router_info['image_version'] = router_dict[str(arg)].image_version
                    if hasattr(router_dict[str(arg)], 'links'):
                        links = router_dict[str(arg)].links
                        for key, value in links.items():
                            router_info['links'].append(key)
                    if hasattr(router_dict[str(arg)], 'interfaces'):
                        interfaces = router_dict[str(arg)].interfaces
                        for key, value in interfaces.items():
                            router_info['interfaces'].append(key)
                    if hasattr(router_dict[str(arg)], 'tftp_server'):
                        router_info['tftp_server'] = router_dict[str(arg)].tftp_server
        print("router info")
        for key , value in router_info.items():
            print(key ,":", value)

    def help_show_locals(self):
        """
        Method help locals
        :return: print help 
        """
        print("""
        This command will print out the names and values of all the local variables.
        """)

    def do_show_locals(self,arg=None):
        """
        Method locals
        :param arg: None
        :return: display all the locals in the session along with dump env 
                in the categorized format like env, devices, feature_lib etc. 
        """
        # Define regular expressions for different categories
        repo_regex = re.compile(r'REPO', re.IGNORECASE)
        path_regex = re.compile(r'PATH', re.IGNORECASE)
        ssh_regex = re.compile(r'SSH', re.IGNORECASE)
        home_regex = re.compile(r'HOME', re.IGNORECASE)
        root_regex = re.compile(r'ROOT', re.IGNORECASE)
        venv_regex = re.compile(r'VIRTUAL', re.IGNORECASE)

        # Define a dictionary to hold the categorized environment variables
        env_vars = {
            'Repo': {},
            'Path': {},
            'SSH': {},
            'Home': {},
            'Root': {},
            'VirtualEnv': {},
            'Other': {}
        }

        # Categorize the environment variables based on their names
        for key, value in os.environ.items():
            if re.search(repo_regex,key):
                env_vars['Repo'][key] = value
            elif re.search(path_regex,key):
                env_vars['Path'][key] = value
            elif re.search(ssh_regex,key):
                env_vars['SSH'][key] = value
            elif re.search(home_regex,key):
                env_vars['Home'][key] = value
            elif re.search(root_regex,key):
                env_vars['Root'][key] = value
            elif re.search(venv_regex,key):
                env_vars['VirtualEnv'][key] = value
            else:
                env_vars['Other'][key] = value

        # Print out the categorized environment variables in a formatted form
        for category, vars_dict in env_vars.items():
            print(f"{category} Variables:")
            print("\t")
            if vars_dict:
                for key, value in vars_dict.items():
                    print(f"\t{key}: {value}")
                print("\t")
            else:
                print("\tNone")

    def help_feature_lib_locals(self):
        """
        Method help feature_lib_locals
        :return: print help 
        """
        print("""
        This command will display all the imported feature_libs.
        """)

    def do_feature_lib_locals(self,arg=None):
        """
        Method Feature lib locals
        :param arg: None
        :return: display feature_libs locals
        """
        feature_lib = {
            'module' : []
        }
        feature_lib_cls = []
        global_dict = globals()
        for global_key , global_value in global_dict.items():
            if hasattr(global_dict[global_key], '__module__'):
                if 'feature_lib' in global_value.__module__:
                    feature_lib_cls.append(global_key)

        feature_lib['module'] = feature_lib_cls
        print("\nFeature_lib Locals")
        for key , value in feature_lib.items():
            print(key ,":", value)

    def help_show_devices(self):
        """
        Method help show_all_devices
        :return: print help
        """
        print("""
        This command will display all Devices.
        """)

    def do_show_devices(self,arg=None):
        """
        Mathod show all devices
        :param arg: None
        :return: display all devices of the loaded topology in the session
        """
        devices = self.testbed_object.get_devices()
        all_devices = []
        for key, value in devices.items():
            all_devices.append(key)
        print("All Devices")
        print(all_devices)

    def help_show_connected_devices(self):
        """
        Method help show_connected_devices
        :return: print help
        """
        print("""
        This command will display all connected Devices.
        """)

    def do_show_connected_devices(self,arg=None):
        """
        Method show connected devices
        :param arg: None
        :return: display connected devices of the loaded topology in the session
        """
        devices = self.testbed_object.get_devices()
        connected_devices = []
        for key, value in devices.items():
            if hasattr(devices[key],"is_connected"):
                if devices[key].is_connected():
                    connected_devices.append(key)
        print("Connected Devices")
        print(connected_devices)
