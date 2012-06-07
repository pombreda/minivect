"""
Adapted from Cython/Compiler/Visitor.py, see this module for detailed
explanations.
"""

import inspect

class TreeVisitor(object):
    """
    Non-mutating visitor. Subclass and implement visit_MyNode methods.
    A user can traverse a foreign AST by implementing Context.getchildren()
    """

    want_access_path = False

    def __init__(self, context):
        self.context = context
        self.dispatch_table = {}
        if self.want_access_path:
            self.access_path = []
        else:
            self._visitchild = self.visit

    def _find_handler(self, obj):
        # to resolve, try entire hierarchy
        cls = type(obj)
        pattern = "visit_%s"
        mro = inspect.getmro(cls)
        handler_method = None
        for mro_cls in mro:
            handler_method = getattr(self, pattern % mro_cls.__name__, None)
            if handler_method is not None:
                return handler_method

        raise RuntimeError("Visitor %r does not accept object: %s" % (self, obj))

    def visit(self, obj, *args):
        "Visit a single child."
        try:
            handler_method = self.dispatch_table[type(obj)]
        except KeyError:
            handler_method = self._find_handler(obj)
            self.dispatch_table[type(obj)] = handler_method
        return handler_method(obj)

    def _visitchild(self, child, parent, attrname, idx):
        self.access_path.append((parent, attrname, idx))
        result = self.visit(child)
        self.access_path.pop()
        return result

    def visit_childlist(self, child, parent=None, attr=None):
        if isinstance(child, list):
            childretval = [self._visitchild(child_node, parent, attr, idx)
                               for idx, child_node in enumerate(child)]
        else:
            childretval = self._visitchild(child, parent, attr, None)
            if isinstance(childretval, list):
                raise RuntimeError(
                    'Cannot insert list here: %s in %r' % (attr, node))

        return childretval

    def visitchildren(self, parent, attrs=None):
        "Visits the children of the given node."
        if parent is None:
            return None

        if attrs is None:
            attrs = self.context.getchildren(parent)

        result = {}
        for attr in attrs:
            child = getattr(parent, attr)
            if child is not None:
                result[attr] = self.visit_childlist(child, parent, attr)

        return result

class VisitorTransform(TreeVisitor):
    """
    Mutating transform. Each attribute is replaced by the result of the
    corresponding visit_MyNode method.
    """

    def visitchildren(self, parent, attrs=None):
        result = super(VisitorTransform, self).visitchildren(parent, attrs)
        for attr, newnode in result.iteritems():
            if not type(newnode) is list:
                setattr(parent, attr, newnode)
            else:
                # Flatten the list one level and remove any None
                newlist = []
                for x in newnode:
                    if x is not None:
                        if type(x) is list:
                            newlist += x
                        else:
                            newlist.append(x)
                setattr(parent, attr, newlist)
        return result

class MayErrorVisitor(TreeVisitor):
    may_error = False

    def visit_Node(self, node):
        self.visitchildren(node)

    def visit_NodeWrapper(self, node):
        self.may_error = (self.may_error or
                          self.context.may_error(node.opaque_node))

    def visit_ForNode(self, node):
        self.visit(node.init)
        self.visit(node.condition)
        self.visit(node.step)

class PrintTree(TreeVisitor):
    indent = 0
    want_access_path = True

    def visit_Node(self, node):
        if self.access_path:
            parent, attr, idx = self.access_path[-1]
        else:
            attr = "(root)"

        print "%s%s: %s" % (self.indent * "  ", attr, type(node).__name__)
        self.indent += 1
        self.visitchildren(node)
        self.indent -= 1