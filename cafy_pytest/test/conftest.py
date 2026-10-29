"""Test stubs for CAFY dependencies not installed in lightweight test envs."""

import sys
import types


def _install_cafy_stubs():
    if "utils.cafyexception" in sys.modules:
        return

    cafyexception = types.ModuleType("utils.cafyexception")

    class CafyBaseException(Exception):
        pass

    class CompositeError(CafyBaseException):
        def __init__(self, exceptions):
            super(CompositeError, self).__init__("composite")
            self.exceptions = exceptions

    class VerificationError(CafyBaseException):
        pass

    class ConfigError(CafyBaseException):
        pass

    class TgenConfigMissingError(CafyBaseException):
        pass

    class TgenCheckTrafficError(CafyBaseException):
        pass

    class TgenLoadConfigError(CafyBaseException):
        pass

    class TgenStartProtocolError(CafyBaseException):
        pass

    class TgenStartTrafficError(CafyBaseException):
        pass

    class TgenInvalidInputError(CafyBaseException):
        pass

    class TgenArpResolveError(CafyBaseException):
        pass

    class TgenServerError(CafyBaseException):
        pass

    class TgenClientError(CafyBaseException):
        pass

    CafyException = types.SimpleNamespace(
        CafyBaseException=CafyBaseException,
        CompositeError=CompositeError,
        VerificationError=VerificationError,
        ConfigError=ConfigError,
        TgenConfigMissingError=TgenConfigMissingError,
        TgenCheckTrafficError=TgenCheckTrafficError,
        TgenLoadConfigError=TgenLoadConfigError,
        TgenStartProtocolError=TgenStartProtocolError,
        TgenStartTrafficError=TgenStartTrafficError,
        TgenInvalidInputError=TgenInvalidInputError,
        TgenArpResolveError=TgenArpResolveError,
        TgenServerError=TgenServerError,
        TgenClientError=TgenClientError,
    )

    cafyexception.CafyException = CafyException
    sys.modules["utils.cafyexception"] = cafyexception

    cafybase = types.ModuleType("utils.cafybase")

    class CafyBase:
        class NoData(CafyBaseException):
            pass

    cafybase.CafyBase = CafyBase
    sys.modules["utils.cafybase"] = cafybase


_install_cafy_stubs()
