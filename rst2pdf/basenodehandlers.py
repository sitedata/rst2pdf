# -*- coding: utf-8 -*-
# See LICENSE.txt for licensing terms
#$HeadURL$
#$LastChangedDate$
#$LastChangedRevision$

import inspect
from log import log, nodeid
from smartypants import smartyPants
import docutils.nodes
from flowables import BoundByWidth


class MetaHelper(type):
    ''' MetaHelper is designed to generically enable a few of the benefits of
        using metaclasses by encapsulating some of the complexity of setting
        them up.

        If a base class uses MetaHelper (by assigning __metaclass__ = MetaHelper),
        then that class (and its metaclass inheriting subclasses) can control
        class creation behavior by defining a couple of helper functions.

        1) A base class can define a _classpreinit function.  This function
           is called during __new__ processing of the class object itself,
           but only during subclass creation (not when the class defining
           the _classpreinit is itself created).

           The subclass object does not yet exist at the time _classpreinit
           is called.  _classpreinit accepts all the parameters of the
           __new__ function for the class itself (not the same as the __new__
           function for the instantiation of class objects!) and must return
           a tuple of the same objects.  A typical use of this would be to
           modify the class bases before class creation.

        2) Either a base class or a subclass can define a _classinit() function.
           This function will be called immediately after the actual class has
           been created, and can do whatever setup is required for the class.
           Note that every base class (but not every subclass) which uses
           MetaHelper MUST define _classinit, even if that definition is None.

         MetaHelper also places an attribute into each class created with it.
         _baseclass is set to None if this class has no superclasses which
         also use MetaHelper, or to the first such MetaHelper-using baseclass.
         _baseclass can be explicitly set inside the class definition, in
         which case MetaHelper will not override it.
    '''
    def __new__(clstype, name, bases, clsdict):
        # Our base class is the first base in the class definition which
        # uses MetaHelper, or None if no such base exists.
        base = ([x for x in bases if type(x) is MetaHelper] + [None])[0]

        # Only set our base into the class if it has not been explicitly
        # set
        clsdict.setdefault('_baseclass', base)

        # See if the base class definied a preinit function, and call it
        # if so.
        preinit = getattr(base, '_classpreinit', None)
        if preinit is not None:
            clstype, name, bases, clsdict = preinit(clstype, name, bases, clsdict)

        # Delegate the real work to type
        return type.__new__(clstype, name, bases, clsdict)

    def __init__(cls, name, bases, clsdict):
        # Let type build the class for us
        type.__init__(cls, name, bases, clsdict)
        # Call the class's initialization function if defined
        if cls._classinit is not None:
            cls._classinit()


class NodeHandler(object):
    ''' NodeHandler classes are used to dispatch
       to the correct class to handle some node class
       type, via a dispatchdict in the main class.
    '''
    __metaclass__ = MetaHelper

    @classmethod
    def _classpreinit(baseclass, clstype, name, bases, clsdict):
        # _classpreinit is called before the actual class is built
        # Perform triage on the class bases to separate actual
        # inheritable bases from the target docutils node classes
        # which we want to dispatch for.

        # Allow multiple class hierarchies to search up to,
        # but not including, NodeHandler
        while 1:
            basebase = getattr(baseclass, '_baseclass', None)
            if basebase in (None, NodeHandler):
                break
            baseclass = basebase

        new_bases = []
        targets = []
        for target in bases:
            if target is not object:
                (targets, new_bases)[issubclass(target, baseclass)].append(target)
        clsdict['_targets'] = targets
        return clstype, name, tuple(new_bases), clsdict

    @classmethod
    def _classinit(cls):
        # _classinit() is called once the subclass has actually
        # been created.

        # For the base class, just add a dispatch dictionary
        if cls._baseclass is None:
            cls.dispatchdict = {}
            return

        # for subclasses, instantiate them, and then add
        # the class to the dispatch dictionary for each of its targets.
        self = cls()
        for target in cls._targets:
            if cls.dispatchdict.setdefault(target, self) is not self:
                t = repr(target)
                old = repr(cls.dispatchdict[target])
                new = repr(self)
                log.debug('Dispatch handler %s for node type %s overridden by %s' %
                    (old, t, new))
                cls.dispatchdict[target] = self

    @classmethod
    def findsubclass(cls, node):
        nodeclass = node.__class__
        log.debug("%s: %s", cls, nodeclass)
        log.debug("[%s]", nodeid(node))
        try:
            log.debug("%s: %s", cls, node)
        except (UnicodeDecodeError, UnicodeEncodeError):
            log.debug("%s: %r", cls, node)

        # Dispatch to the first matching class in the MRO

        dispatchdict = cls.dispatchdict
        for baseclass in inspect.getmro(nodeclass):
            self = dispatchdict.get(baseclass)
            if self is not None:
                break
        else:
            self = cls.default_dispatch
        return self


class GenElements(NodeHandler):
    _baseclass = None

    # Begin overridable attributes and methods for GenElements

    def gather_elements(self, client, node, style):
        return client.gather_elements(node, style=style)

    # End overridable attributes and methods for GenElements

    @classmethod
    def dispatch(cls, client, node, style=None):
        self = cls.findsubclass(node)

        # set anchors for internal references
        try:
            for i in node['ids']:
                client.pending_targets.append(i)
        except TypeError: #Happens with docutils.node.Text
            pass


        try:
            if node['classes'] and node['classes'][0]:
                # FIXME: Supports only one class, sorry ;-)
                if client.styles.StyleSheet.has_key(node['classes'][0]):
                    style = client.styles[node['classes'][0]]
                else:
                    log.info("Unknown class %s, ignoring. [%s]",
                        node['classes'][0], nodeid(node))
        except TypeError: # Happens when a docutils.node.Text reaches here
            pass

        if style is None or style == client.styles['bodytext']:
            style = client.styles.styleForNode(node)

        elements = self.gather_elements(client, node, style)

        # Make all the sidebar cruft unreachable
        #if style.__dict__.get('float','None').lower() !='none':
            #node.elements=[Sidebar(node.elements,style)]
        #elif 'width' in style.__dict__:

        if 'width' in style.__dict__:
            elements = [BoundByWidth(style.width,
                elements, style, mode="shrink")]

        if node.line and client.debugLinesPdf:
            elements.insert(0,TocEntry(client.depth-1,'LINE-%s'%node.line))
        node.elements = elements
        return elements


class GenPdfText(NodeHandler):
    _baseclass = None

    # Begin overridable attributes and methods for gen_pdftext

    pre = ''
    post = ''

    def get_pre_post(self, client, node, replaceEnt):
        return self.pre, self.post

    def get_text(self, client, node, replaceEnt):
        return client.gather_pdftext(node)

    def apply_smartypants(self, text, smarty, node):
        # Try to be clever about when to use smartypants
        if node.__class__ in (docutils.nodes.paragraph,
                docutils.nodes.block_quote, docutils.nodes.title):
            return smartyPants(text, smarty)
        return text

    # End overridable attributes and methods for gen_pdftext

    @classmethod
    def dispatch(cls, client, node, replaceEnt=True):
        self = cls.findsubclass(node)
        pre, post = self.get_pre_post(client, node, replaceEnt)
        text = self.get_text(client, node, replaceEnt)
        text = pre + text + post

        try:
            log.debug("self.gen_pdftext: %s" % text)
        except UnicodeDecodeError:
            pass

        text = self.apply_smartypants(text, client.smarty, node)
        node.pdftext = text
        return text