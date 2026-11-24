import os
class CafyGTA_Configs:
    GTA_URL = 'https://cafy3.cisco.com/api/gta'
    API_KEY = os.environ.get("API_KEY", None)
    @staticmethod
    def get_gta_url():
        """
        return GTA_Url
        """
        return CafyGTA_Configs.GTA_URL

    @staticmethod
    def get_api_key():
        """
        return Api Key 
        """
        return CafyGTA_Configs.API_KEY
