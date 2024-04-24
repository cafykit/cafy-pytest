import time
import pytest
from cafy_pytest.cafy_gta import TimeCollectorPlugin

@pytest.fixture
def plugin():
    """
    Fixture to provide an instance of TimeCollectorPlugin for testing.
    """
    return TimeCollectorPlugin()

class TestTimeCollectorPlugin:
    """
    Test cases for the TimeCollectorPlugin class.
    """

    def test_update_granular_time_testcase_dict(self, plugin):
        """
        Test the update_granular_time_testcase_dict method.
        """
        current_test = "test_case_1"
        event = "sleep_time"
        method_name = "TestClass.sleep"
        elapsed_time = "1.23"

        plugin.update_granular_time_testcase_dict(current_test, event, method_name, elapsed_time)

        assert current_test in plugin.granular_time_testcase_dict
        assert plugin.granular_time_testcase_dict[current_test][event][method_name][0] == float(elapsed_time)

    def test_measure_time_for_set_or_get_methods(self, plugin):
        """
        Test the measure_time_for_set_or_get_methods method.
        """
        def mock_method(*args, **kwargs):
            return "mocked result"

        cls_name = "TestClass"
        method = mock_method

        wrapper = plugin.measure_time_for_set_or_get_methods(method, cls_name)
        result = wrapper()

        assert result == "mocked result"

    def test_measure_sleep_time(self, plugin, mocker):
        """
        Test the measure_sleep_time method.
        """
        # Mocking data
        duration = 1.5
        mocker.patch.object(plugin, 'original_sleep')

        # Set the test case name
        plugin.test_case_name = "test_case_1"

        # Call the method
        mocker.patch('time.perf_counter', side_effect=[0, 1.5])
        plugin.measure_sleep_time(duration)

        # Check if the original_sleep method is called
        plugin.original_sleep.assert_called_once_with(duration)

        # Check if the granular time is updated correctly
        assert plugin.granular_time_testcase_dict["test_case_1"]["sleep_time"]["TestTimeCollectorPlugin.test_measure_sleep_time.time.sleep"][0] == float(1.5)


    def test_patch_set_or_get_methods_for_test_instance(self, plugin):
        """
        Test the patch_set_or_get_methods_for_test_instance method.
        """
        item = type("MockItem", (), {"cls": type("MockClass", (), {"setup_method": None, "set_method": None})})()
        plugin.patch_set_or_get_methods_for_test_instance(item)

        # Check if methods are patched correctly
        assert item.cls.setup_method is None
        assert item.cls.set_method is None

    def test_update_CafyLog_gta_dict(self, plugin):
        """
        Test the update_CafyLog_gta_dict method.
        """
        current_test = "test_case_1"
        plugin.granular_time_testcase_dict = {
            current_test: {
                "set_command": {"method1": [1.23]},
                "get_command": {"method2": [2.34]}
            }
        }

        plugin.update_CafyLog_gta_dict(current_test)

        assert current_test in plugin.granular_time_testcase_dict
        assert "set_command" in plugin.granular_time_testcase_dict[current_test]
        assert "get_command" in plugin.granular_time_testcase_dict[current_test]

    def test_get_time_data(self, plugin):
        """
        Test the get_time_data method.
        """
        data = {"method1": [1.23, 2.34], "method2": [3.45, 4.56]}
        event = "sleep_time"

        result = plugin.get_time_data(data, event)

        assert "method1" in result
        assert "method2" in result
        assert result["method1"][0] == "3.57"
        assert result["method1"][1] == 2
        assert result["method2"][0] == "8.01"
        assert result["method2"][1] == 2

    def test_collect_granular_time_accouting_report(self, plugin):
        """
        Test the collect_granular_time_accouting_report method.
        """
        plugin.granular_time_testcase_dict = {
            "test_case_1": {
                "sleep_time": {"method1": [1.23]},
                "set_command": {"method2": [2.34]},
                "get_command": {"method3": [3.45]}
            }
        }

        result = plugin.collect_granular_time_accouting_report()

        assert "test_case_1" in result
        assert result["test_case_1"]["sleep_time"]["method1"][0] == "1.23"
