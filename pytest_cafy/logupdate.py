import re
import sys
from jinja2 import Template

class HtmlWriter:
    def tag(self,tag,data,klass=None,**kwargs):
        optstr = ""
        if klass is not None:
            optstr = "class='{klass}'".format(klass=klass)
        for key,value in kwargs.items():
            optstr = optstr + "{key}={value}".format(key=key,value=value)
        print("<{tag} {optstr}>{data}</{tag}>".format(tag=tag,optstr=optstr,data=data))

    def span(self,data,**kwargs):
        return self.tag("span",data,**kwargs)

    def div(self,data,**kwargs):
        return self.tag("div",data,**kwargs)
htmlwriter = HtmlWriter()


print("""
<!doctype html>
<html lang="en">
  <head>
    <!-- Required meta tags -->
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">

    <!-- Bootstrap CSS -->
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.1.0/css/bootstrap.min.css" integrity="sha384-9gVQ4dYFwwWSjIDZnLEWnxCjeSWFphJiwGPXr1jddIhOegiu1FwO5qRGvFXOdJZ4" crossorigin="anonymous">
    <link href="https://fonts.googleapis.com/css?family=Source+Code+Pro" rel="stylesheet">
    <title>all.log</title>
    <style type="text/css">
    div.collapse { 
    font-family: 'Source Code Pro', monospace;
    }
    </style>
  </head>
  <body>
  
  


  <div class="container-fluid">
  <div class="row">
  <div class="col-12">
<br/><br/>

  
  


 
""")


class LogParser:
    class LogObject:
        def __init__(self, timestamp, message, thread, logger):
            self.data = {
                'timestamp' : timestamp,
                'message' : message,
                'thread' : thread,
                'etype' : self.__class__.__name__.lower(),
                'logger' : logger
            }

        def xaccept(self):
            pass
        def accept(self):
            print("""
            <div class="row log-{etype}" style="border-bottom: 1px solid #ededed">
                <div class=col-1>{etype}</div>
                <div class=col-2>{timestamp}</div>
                <div class=col-1 title={logger}  style="white-space: nowrap; 
    overflow: hidden;
    text-overflow: ellipsis;">{logger}</div>
                <div class=col-7>{message}</div>
            </div>
            """.format(**self.data))

    class Info(LogObject):
       pass

    class Warning(LogObject):
        pass

    class Debug(LogObject):
        pass

    class Out(LogObject):
        def accept(self):
            print("""
            <div class="row log-{etype}" style="border-bottom: 1px solid #ededed">
                <div class=col-1>{etype}</div>
                <div class=col-2>{timestamp}</div>
                <div class=col-1 title={logger} style="white-space: nowrap; 
    overflow: hidden;
    text-overflow: ellipsis;">{logger}</div>
                <div class=col-7><div class="alert alert-info" role="alert">{message}</div></div>
            </div>
            """.format(**self.data))



    class Error(LogObject):
        pass

    class LogList(LogObject):
        def __init__(self,name):
            self.logs = list()

        def add(self,obj):
            self.logs.append(obj)

        def accept(self):
            pass

    class ThreadLog(LogList):
        def __init__(self,name):
            self.thread = name
            self.thread_logs = dict()
            self.id = 1

        def add(self,thread, obj):
            if thread not in self.thread_logs:
                self.thread_logs[thread]=list()
            self.thread_logs[thread].append(obj)


        def accept(self):
            self.id = self.id+1
            thread_id = 0
            thread_id_lookup = dict()

            print("""
            <div class="card">
            <div class="card-header">
                Threaded logs begin from here
            </div>
            <div style="padding-left:5px; padding-right:5px">
            <ul class="nav nav-tabs" id="myTab{id}" role="tablist">""".format(id=self.id))

            extra="active"
            selected="true"
            for thread,logs in self.thread_logs.items():
                thread_id_lookup[thread] = thread_id
                thread_id = thread_id + 1
                print("""
                    <li class="nav-item">
                        <a class=  "nav-link {extra}" id="home-tab{id}{thread_id}" data-toggle="tab" href="#home{id}{thread_id}" role="tab" aria-controls="home{id}{thread_id}" aria-selected="{selected}">{thread}</a>
                    </li>
                      """.format(id=self.id,thread=thread,thread_id=thread_id_lookup[thread],extra=extra,selected=selected))
                extra = ""
                selected = "false"
            print("""</ul>""")

            print("""<div class="tab-content" id="myTabContent{id}">""".format(id=self.id))
            extra = "show active"
            for thread, logs in self.thread_logs.items():
                print("""
                        <div class="tab-pane fade {extra}" id="home{id}{thread_id}" role="tabpanel" aria-labelledby="home-tab{id}{thread_id}">
                    """.format(id=self.id,thread=self.thread,thread_id=thread_id_lookup[thread],extra = extra))
                extra = ""
                for log in logs:
                   log.accept()
                print("""</div>""")


            print("""</div></div>""")
            print("""<div class="card-footer"> Threaded logs End </div>""")
            print("""</div>""")






    class TestcaseLog(LogList):
        TID = 1
        def __init__(self,testcase):
            self.testcase = testcase
            self.logs = list()
            self.id = LogParser.TestcaseLog.TID
            if self.id == 1:
                self.show = "show"
                self.expanded = "true"
            else:
                self.show = ""
                self.expanded = "false"
            LogParser.TestcaseLog.TID = LogParser.TestcaseLog.TID + 1



        def accept(self):


            print("""
                            <div class="card">
                <div class="card-header" id="headingOne{id}">
                  <h5 class="mb-0">
                    <button class="btn btn-link" data-toggle="collapse" data-target="#collapseOne{id}" aria-expanded="{expanded}" aria-controls="collapseOne{id}">
                      {testcase}
                    </button>
                  </h5>
                </div>

                <div id="collapseOne{id}" class="collapse " aria-labelledby="headingOne{id}" data-parent="#accordion">
                  <div class="card-body">
                    
                      
                            """.format(id=self.id, testcase=self.testcase, show=self.show, expanded=self.expanded))
            for log in self.logs:

                log.accept()

            print("""</div>
                </div>
              </div>""")

    MatchClass = {
        'Info': Info,
        'Warning': Warning,
        'Debug' : Debug,
        'Error' : Error,
        'Out' : Out
    }

    def __init__(self,logfile):
        self.logfile = logfile
        self.id = 1
        self.testcases = list()

    def bootstrap_begin_accordion(self):
        print("""<div class="accordionxz" id="accordion">""")

    def bootstrap_end_accordion(self):
        print("</div>")





    def parse(self):
        f = open(self.logfile, 'r')
        last_output = None
        logsep = re.compile("-(\w+)\-*?(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\[(.*?)\]\[(.*?)\]>(.*$)")
        current_tag = None
        current_testcase = self.TestcaseLog("setup_module")
        thread_logger = None
        output = ""
        self.bootstrap_begin_accordion()

        for line in f:
            result = logsep.match(line)
            if result:
                if current_tag is not None:
                    klass = LogParser.MatchClass.get(current_tag, None)
                    if klass is not None:
                        data = klass(timestamp=timestamp, message=output, thread=thread, logger=logger)
                        if thread_logger is not None:
                            thread_logger.add(thread,data)
                        else:
                            current_testcase.add(data)

                current_tag = result.group(1)
                timestamp = result.group(2)
                logger = result.group(4)
                thread = result.group(3)
                message = result.group(5)

                #if thread != "MainThread":
                #if thread_logger is not None None:
                    #    thread_logger = self.ThreadLog(thread)
                #   current_testcase.add(thread_logger)

                if 'BEGIN THREAD' in message or 'verification(parallel) starts' in message :
                    thread_logger = self.ThreadLog(thread)
                    current_testcase.add(thread_logger)

                if 'END THREAD' in message or 'verification(parallel) ends' in message :
                    thread_logger = None



                tcmatch = re.compile("\s*Start test\:\s+(.*)\s*$")
                if current_tag == "Title":
                    testcase = tcmatch.match(message)
                    if testcase:
                        # print("Found: %s" % testcase.group(1))
                        #import ipdb;
                        #ipdb.set_trace()

                        if current_testcase is not None:
                            current_testcase.accept()
                        current_testcase = self.TestcaseLog(testcase.group(1))

                output = "<div>{line}</div>".format(line=result.group(5).strip())
            else:
                output = output + "<div>{line}</div>".format(line=line.strip())
        f.close()
        if current_testcase is not None:
            current_testcase.accept()
        self.bootstrap_end_accordion()

logparser = LogParser(sys.argv[1])
print("""<div id="accordion">""")

logparser.parse()
print("""</div>""")

mapButtons = {
    'info' : 'info',
    'warning' : 'warning',
    'out' : 'secondary',
    'error': 'danger',
    'fail' : 'danger',
    'success' : 'success',
    'debug' : 'primary'

}

navbar = Template("""
    </div>
    </div>
    </div>


<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
  <a class="navbar-brand" href="#">Cafy</a>
  <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarSupportedContent" aria-controls="navbarSupportedContent" aria-expanded="false" aria-label="Toggle navigation">
    <span class="navbar-toggler-icon"></span>
  </button>

  <div class="collapse navbar-collapse" id="navbarSupportedContent">
    <ul class="navbar-nav mr-auto">
      <li class="nav-item dropdown">
        <a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
          Anchors
        </a>
        <div class="dropdown-menu" aria-labelledby="navbarDropdown">
        </div>
      </li>
      
    <li class="nav-item">
    <div class="btn-group" role="group" aria-label="Basic example">
    {% for cf,bs in mapButtons.items() %}
        <button type="button" class="btn btn-{{bs}}" id="btn-{{cf}}">{{cf}}</button>
    {%endfor%}
       


    </div>
    </li>

      

    </ul>

    <form class="form-inline my-2 my-lg-0">
      <input class="form-control mr-sm-2" type="search" placeholder="Search" aria-label="Search">
      <button class="btn btn-outline-success my-2 my-sm-0" type="submit">Search</button>
    </form>
  </div>
</nav>
    <!-- Optional JavaScript -->
    <!-- jQuery first, then Popper.js, then Bootstrap JS -->
    <script src="https://code.jquery.com/jquery-3.3.1.slim.min.js" integrity="sha384-q8i/X+965DzO0rT7abK41JStQIAqVgRVzpbzo5smXKp4YfRvH+8abtTE1Pi6jizo" crossorigin="anonymous"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/popper.js/1.14.0/umd/popper.min.js" integrity="sha384-cs/chFZiN24E4KMATLdqdvsezGxaGsi4hLGOzlXwp5UZB1LY//20VyM2taTB4QvJ" crossorigin="anonymous"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.1.0/js/bootstrap.min.js" integrity="sha384-uefMccjFJAIv6A+rW+L4AHf99KvxDjWSu1z9VI8SKNVmz4sk7buKt/6v9KI65qnm" crossorigin="anonymous"></script>
    <script type="text/javascript">
    {% for cf,bs in mapButtons.items() %}
    $("#btn-{{cf}}").click(function () {
        $(".log-{{cf}}").toggle()
        $(this).toggleClass("btn-outline-{{bs}}")
        $(this).toggleClass("btn-{{bs}}")
    });
    {%endfor%}
    </script>
  </body>
</html>
""")


print(navbar.render(mapButtons=mapButtons))

"""
last_testclass = None
for tc in logparser.testcases:
    id = tc['id']
    testcase = tc['testcase']
    tci = testcase.split(".")
    if len(tci) > 1:
        testclass = tci[0]
        testname = tci[1]
    else:
        testclass = "*"
        testname = tci[0]

    if testclass != last_testclass:
        <div class="dropdown-divider">{testclass}</div>
        <a class="dropdown-item disabled" href="#">{testclass}</a>.format(id=id,testclass=testclass))
    last_testclass = testclass
    <a class="dropdown-item" href="#heading{id}">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{testcase}</a>.format(id=id,testcase=testname))
    #<div class="dropdown-divider"></div>


"""
