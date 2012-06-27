"""
Copyright (c) 2012 Fredrik Ehnbom

This software is provided 'as-is', without any express or implied
warranty. In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

   1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.

   2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.

   3. This notice may not be removed or altered from any source
   distribution.

#### MODIFIED BY Nick Lloyd
"""
import sublime
import sublime_plugin
import re
import subprocess
import time
import Queue
import threading
from parsehelp import parsehelp
reload(parsehelp)

language_regex = re.compile("(?<=source\.)[\w+#]+")
member_regex = re.compile("(([a-zA-Z_]+[0-9_]*)|([\)\]])+)(\.)$")


class CompletionCommonDotComplete(sublime_plugin.TextCommand):
    def run(self, edit):
        for region in self.view.sel():
            self.view.insert(edit, region.end(), ".")
        caret = self.view.sel()[0].begin()
        line = self.view.substr(sublime.Region(self.view.word(caret-1).a, caret))
        if member_regex.search(line) != None:
            sublime.set_timeout(self.delayed_complete, 1)

    def delayed_complete(self):
        self.view.run_command("auto_complete")


class CompletionCommon(object):

    def __init__(self, settingsfile, workingdir):
        self.settingsfile = settingsfile
        self.completion_proc = None
        self.completion_cmd = None
        self.data_queue = Queue.Queue()
        self.workingdir = workingdir

    def get_settings(self):
        print 'getting settings file: %s' % self.settingsfile
        return sublime.load_settings(self.settingsfile)

    def get_setting(self, key, default=None):
        print 'getting setting: %s' % key
        try:
            s = sublime.active_window().active_view().settings()
            if s.has(key):
                return s.get(key)
        except:
            pass
        return self.get_settings().get(key, default)

    def get_cmd(self):
        return None

    def error_thread(self):
        try:
            while True:
                if self.completion_proc.poll() != None:
                    break
                print "stderr: %s" % (self.completion_proc.stderr.readline().strip())
        finally:
            pass

    def completion_thread(self):
        try:
            print "running completion_thread"
            while True:
                if self.completion_proc.poll() != None:
                    break
                read = self.completion_proc.stdout.readline().strip()
                if read:
                    self.data_queue.put(read)
        finally:
            self.data_queue.put(";;--;;")
            self.data_queue.put(";;--;;exit;;--;;")
            self.completion_cmd = None
            print "completion_thread terminated"

    def run_completion(self, cmd, stdin=None):
        print "run_completion w cmd: %s" % cmd
        realcmd = self.get_cmd()
        # print "self.completion_proc?: %s" % self.completion_proc
        # print "self.completion_cmd?: %s" % self.completion_cmd
        # print "self.completion_proc.poll()?: %s" % self.completion_proc.poll()
        if not self.completion_proc or realcmd != self.completion_cmd or self.completion_proc.poll() != None:
            if self.completion_proc:
                if self.completion_proc.poll() == None:
                    self.completion_proc.stdin.write("-quit\n")
                while self.data_queue.get() != ";;--;;exit;;--;;":
                    continue

            print 'starting a new completion_thread proc'
            self.completion_cmd = realcmd
            self.completion_proc = subprocess.Popen(
                realcmd,
                cwd=self.workingdir,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
                )
            t = threading.Thread(target=self.completion_thread)
            t.start()
            t = threading.Thread(target=self.error_thread)
            t.start()
        towrite = cmd + "\n"
        if stdin:
            towrite += stdin + "\n"
        self.completion_proc.stdin.write(towrite)
        stdout = ""
        while True:
            try:
                read = self.data_queue.get(timeout=5.0)
                if read == ";;--;;" or read == None:
                    break
                stdout += read+"\n"
            except:
                break
        print "post-proc-init: %s" % stdout
        return stdout

    def get_language(self, view=None):
        if view == None:
            view = sublime.active_window().active_view()
        caret = view.sel()[0].a
        scope = view.scope_name(caret).strip()
        language = language_regex.search(scope)
        if language == None:
            if scope.endswith("jsp"):
                return "jsp"
            return None
        print 'get_language: %s' % language.group(0)
        return language.group(0)

    def is_supported_language(self, view):
        return False

    def get_packages(self, data, thispackage, type):
        return []

    def find_absolute_of_type(self, data, full_data, type, template_args=[]):
        print "find_absolute_of_type: %s" % type
        thispackage = re.search("[ \t]*package (.*);", data)
        if thispackage is None:
            thispackage = ""
        else:
            thispackage = thispackage.group(1)
        sepchar = "$"
        if self.get_language() == "cs":
            sepchar = "+"
            thispackage = re.findall(r"\s*namespace\s+([\w\.]+)\s*{", parsehelp.remove_preprocessing(data), re.MULTILINE)
            thispackage = ".".join(thispackage)

        match = re.search("class %s" % type, full_data)
        if not match is None:
            # This type is defined in this file so figure out the nesting
            full_data = parsehelp.remove_empty_classes(parsehelp.collapse_brackets(parsehelp.remove_preprocessing(full_data[:match.start()])))
            regex = re.compile("\s*class\s+([^\\s{]+)")
            add = ""
            for m in re.finditer(regex, full_data):
                if len(add):
                    add = "%s%s%s" % (add, sepchar, m.group(1))
                else:
                    add = m.group(1)

            if len(add):
                type = "%s%s%s" % (add, sepchar, type)
            # Class is defined in this file, return package of the file
            if len(thispackage) == 0:
                return type
            return "%s.%s" % (thispackage, type)

        packages = self.get_packages(data, thispackage, type)
        packages.append(";;--;;")

        output = self.run_completion("-findclass;;--;;%s" % (type), "\n".join(packages)).strip()
        if len(output) == 0 and "." in type:
            return self.find_absolute_of_type(data, full_data, type.replace(".", sepchar), template_args)
        return output

    def complete_class(self, absolute_classname, prefix, template_args=""):
        print "complete_class: %s, prefix: %s" % (absolute_classname, prefix)
        stdout = self.run_completion("-complete;;--;;%s;;--;;%s%s%s" % (absolute_classname, prefix, ";;--;;" if len(template_args) else "", template_args))
        stdout = stdout.split("\n")[:-1]
        members = [tuple(line.split(";;--;;")) for line in stdout]
        ret = []
        for member in members:
            if len(member) == 3:
                member = (member[0], member[1], int(member[2]))
            if member not in ret:
                ret.append(member)
        return sorted(ret, key=lambda a: a[0])

    def get_return_type(self, absolute_classname, prefix, template_args=""):
        print 'get_return_type: %s, prefix: %s' % (absolute_classname, prefix)
        stdout = self.run_completion("-returntype;;--;;%s;;--;;%s%s%s" % (absolute_classname, prefix, ";;--;;" if len(template_args) else "", template_args))
        ret = stdout.strip()
        match = re.search("(\[L)?([^;]+)", ret)
        if match:
            return match.group(2)
        return ret

    def patch_up_template(self, data, full_data, template):
        print 'patch_up_template: %s' % data
        if template == None:
            return None
        ret = []
        for param in template:
            name = self.find_absolute_of_type(data, full_data, param[0], param[1])
            ret.append((name, self.patch_up_template(data, full_data, param[1])))
        return ret

    def return_completions(self, comp):
        if self.get_setting("completioncommon_inhibit_sublime_completions", True):
            return (comp, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        return comp

    def is_static(self, mod):
        return (mod&(1<<0)) != 0

    def is_private(self, mod):
        return (mod&(1<<1)) != 0

    def is_protected(self, mod):
        return (mod&(1<<2)) != 0

    def is_public(self, mod):
        return (mod&(1<<3)) != 0

    def filter(self, typename, var, isstatic, data, indata):
        print 'filter: typename=%s, var=%s, isstatic=%s' % (typename, var, isstatic)
        ret = []
        if len(indata) > 0 and len(indata[0]) == 2:
            # Filtering info not available
            return indata

        mypackage = None
        lang = self.get_language()
        if lang == "java" or lang == "jsp":
            mypackage = parsehelp.extract_package(data)
        else:
            mypackage = parsehelp.extract_namespace(data)
            if mypackage != None:
                mypackage = mypackage.replace("::", ".")
        if mypackage == None:
            mypackage = ""
        idx = typename.rfind(".")
        if idx == -1:
            idx = 0
        typepackage = typename[:idx]
        samepackage = mypackage == typepackage

        for disp, ins, mod in indata:
            public = self.is_public(mod)
            static = self.is_static(mod)
            accessible = public or (samepackage and not self.is_private(mod))

            if var == "this":
                ret.append((disp, ins))
            elif isstatic and static and accessible:
                ret.append((disp, ins))
            elif not isstatic and accessible:
                ret.append((disp, ins))
        return ret

    def on_query_completions(self, view, prefix, locations):
        print "on_query_completions: prefix::%s" % prefix
        bs = time.time()
        start = time.time()
        if not self.is_supported_language(view):
            return []
        line = view.substr(sublime.Region(view.full_line(locations[0]).begin(), locations[0]))
        before = line
        if len(prefix) > 0:
            before = line[:-len(prefix)]
        if re.search("[ \t]+$", before):
            before = ""
        elif re.search("\.$", before):
            # Member completion
            data = view.substr(sublime.Region(0, locations[0]-len(prefix)))
            full_data = view.substr(sublime.Region(0, view.size()))
            typedef = parsehelp.get_type_definition(data)
            if typedef == None:
                return self.return_completions([])
            line, column, typename, var, tocomplete = typedef
            print typedef
            # TODO: doesn't understand arrays at the moment
            tocomplete = tocomplete.replace("[]", "")

            if typename is None:
                # This is for completing for example "System."
                # or "String." or other static calls/variables
                typename = var
                var = None
            start = time.time()
            template = parsehelp.solve_template(typename)
            if template[1]:
                template = template[1]
            else:
                template = ""
            template = self.patch_up_template(data, full_data, template)
            typename = re.sub("(<.*>)|(\[.*\])", "", typename)
            oldtypename = typename
            typename = self.find_absolute_of_type(data, full_data, typename, template)
            if typename == "":
                # Possibly a member of the current class
                clazz = parsehelp.extract_class(data)
                if clazz != None:
                    var = "this"
                    typename = self.find_absolute_of_type(data, full_data, clazz, template)
                    tocomplete = "." + oldtypename + tocomplete

            end = time.time()
            print "absolute is %s (%f ms)" % (typename, (end-start)*1000)
            if typename == "":
                return self.return_completions([])

            tocomplete = tocomplete[1:]  # skip initial .
            if len(tocomplete):
                # Just to make sure that the var isn't "this"
                # because in the end it isn't "this" we are
                # completing, but something else
                var = None

            isstatic = False
            if len(tocomplete) == 0 and var == None:
                isstatic = True
            start = time.time()
            idx = tocomplete.find(".")
            while idx != -1:
                sub = tocomplete[:idx]
                idx2 = sub.find("(")
                if idx2 >= 0:
                    sub = sub[:idx2]
                    count = 1
                    for i in range(idx+1, len(tocomplete)):
                        if tocomplete[i] == '(':
                            count += 1
                        elif tocomplete[i] == ')':
                            count -= 1
                            if count == 0:
                                idx = tocomplete.find(".", i)
                                break
                tempstring = ""
                if template:
                    for param in template:
                        if len(tempstring):
                            tempstring += ";;--;;"
                        tempstring += parsehelp.make_template(param)
                if "<" in sub and ">" in sub:
                    temp = parsehelp.solve_template(sub)
                    temp2 = self.patch_up_template(data, full_data, temp[1])
                    temp = (temp[0], temp2)
                    temp = parsehelp.make_template(temp)
                    sub = "%s%s" % (temp, sub[sub.rfind(">")+1:])

                n = self.get_return_type(typename, sub, tempstring)
                print "%s%s.%s = %s" % (typename, "<%s>" % tempstring if len(tempstring) else "", sub, n)
                if len(n) == 0:
                    return self.return_completions([])
                n = parsehelp.get_base_type(n)
                template = parsehelp.solve_template(n)
                typename = template[0]
                if self.get_language() == "cs" and len(template) == 3:
                    typename += "`%d+%s" % (len(template[1]), parsehelp.make_template(template[2]))
                template = template[1]
                tocomplete = tocomplete[idx+1:]
                idx = tocomplete.find(".")
            end = time.time()
            print "finding what to complete took %f ms" % ((end-start) * 1000)

            template_args = ""
            if template:
                for param in template:
                    if len(template_args):
                        template_args += ";;--;;"
                    template_args += parsehelp.make_template(param)

            print "completing %s%s.%s" % (typename, "<%s>" % template_args if len(template_args) else "", prefix)
            start = time.time()
            ret = self.complete_class(typename, prefix, template_args)
            ret = self.filter(typename, var, isstatic, data, ret)
            end = time.time()
            print "completion took %f ms" % ((end-start)*1000)
            be = time.time()
            print "total %f ms" % ((be-bs)*1000)
            if self.get_setting("completioncommon_shorten_names", True):
                old = ret
                ret = []
                regex = re.compile("([\\w\\.]+\\.)*")
                for display, insert in old:
                    olddisplay = display
                    display = regex.sub("", display)
                    while olddisplay != display:
                        olddisplay = display
                        display = regex.sub("", display)
                    ret.append((display, insert))
            return self.return_completions(ret)
        return []

    def on_query_context(self, view, key, operator, operand, match_all):
        print 'on_query_context: key=%s, operator=%s, operand=%s' % (key, operator, operand)
        if key == "completion_common.is_code":
            caret = view.sel()[0].a
            scope = view.scope_name(caret).strip()
            return re.search("(string.)|(comment.)", scope) == None
