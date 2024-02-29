class CafyGTA_Configs:
    GTA_URL = 'https://cafy3.cisco.com:3300/api/gta'
    API_KEY = 'f912594816b83760756f3cfdcb32f08bdf3f9b6fe46183323ec0aaf0e4afe25b'
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
    
