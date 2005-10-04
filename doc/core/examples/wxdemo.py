# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


from wxPython.wx import *

from twisted.internet import wxreactor
wxreactor.install()
from twisted.internet import reactor


# set up so that "hello, world" is printed once a second
def helloWorld():
    print "hello, world"
    reactor.callLater(1, helloWorld)
reactor.callLater(1, helloWorld)

def twoSecondsPassed():
    print "two seconds passed"

reactor.callLater(2, twoSecondsPassed)

ID_EXIT  = 101
ID_DIALOG = 102

class MyFrame(wxFrame):
    def __init__(self, parent, ID, title):
        wxFrame.__init__(self, parent, ID, title, wxDefaultPosition, wxSize(300, 200))
        menu = wxMenu()
        menu.Append(ID_DIALOG, "D&ialog", "Show dialog")
        menu.Append(ID_EXIT, "E&xit", "Terminate the program")
        menuBar = wxMenuBar()
        menuBar.Append(menu, "&File")
        self.SetMenuBar(menuBar)
        EVT_MENU(self, ID_EXIT,  self.DoExit)
        EVT_MENU(self, ID_DIALOG,  self.DoDialog)
    
    def DoDialog(self, event):
        dl = wxMessageDialog(self, "Check terminal to see if messages are still being "
                             "printed by Twisted.")
        dl.ShowModal()
        dl.Destroy()
    
    def DoExit(self, event):
        self.Close(true)
        reactor.stop()


class MyApp(wxApp):

    def OnInit(self):
        frame = MyFrame(NULL, -1, "Hello, world")
        frame.Show(true)
        self.SetTopWindow(frame)
        return true


def demo():
    app = MyApp(0)
    reactor.registerWxApp(app)
    reactor.run(0)


if __name__ == '__main__':
    demo()
