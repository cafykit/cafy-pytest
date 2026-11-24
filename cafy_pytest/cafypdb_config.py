import os
class CafyPdb_Configs:
    Webex_Notification_Url = 'https://cafy3.cisco.com:3500/api/notifications/sns/cafypdb'
    API_KEY = os.environ.get("API_KEY", None)
    connection_timeout = 7200
    doc_link = 'http://cafy-web-sjc1/pages/Cafykit/Develop/cafypdb'
   
    @staticmethod
    def get_webex_url():
        """
        return Webex_Notification_Url
        """
        return CafyPdb_Configs.Webex_Notification_Url
    
    @staticmethod
    def get_api_key():
        """
        return Api Key 
        """
        return CafyPdb_Configs.API_KEY

    @staticmethod
    def get_connection_timeout():
        """
        return connection time out in sec(2hr = 7200 sec)
        """
        return CafyPdb_Configs.connection_timeout

    @staticmethod
    def get_cafypdb_doc():
        """
        return cafypdb documentaion
        """
        return CafyPdb_Configs.doc_link

