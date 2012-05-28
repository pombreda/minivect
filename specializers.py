"""
Specializers for various sorts of data layouts and memory alignments.
"""

import copy

import minivisitor
import minitypes

class ASTMapper(minivisitor.VisitorTransform):

    def __init__(self, context):
        super(ASTMapper, self).__init__(context)
        self.astbuilder = context.astbuilder

    def getpos(self, opaque_node):
        return self.context.getpos(opaque_node)

    def map_type(self, opaque_node):
        return self.context.typemapper.map_type(
                        self.context.gettype(opaque_node))

    def visit(self, node, *args):
        prev = self.astbuilder.pos
        self.astbuilder.pos = self.context.getpos(node)
        result = super(ASTMapper, self).visit(node)
        self.astbuilder.pos = prev
        return result

class Specializer(ASTMapper):
    """
    Implement visit_* methods to specialize to some pattern. The default is
    to copy the node and specialize the children.
    """

    def __init__(self, context, specialization_name):
        super(Specializer, self).__init__(context)
        self.specialization_name = specialization_name
        self.variables = {}
        self.error_handlers = []

    def getpos(self, node):
        return node.pos

    def visit(self, node, *args):
        result = super(Specializer, self).visit(node)
        if result is not None:
            result.is_specialized = True
        return result

    def visit_Node(self, node):
        node = copy.copy(node)
        self.visitchildren(node)
        return node

    def visit_Variable(self, node):
        if node.name not in self.variables:
            self.variables[node.name] = node
        return self.visit_Node(node)

class StridedSpecializer(Specializer):

    def visit_FunctionNode(self, node):
        node.specialization_name = self.specialization_name
        b = self.astbuilder
        node.body = b.stats(node.body, b.return_(node.success_value))
        self.function = node
        self.visitchildren(node)
        return node

    def visit_NDIterate(self, node):
        b = self.astbuilder

        self.indices = []
        body = node.body

        for i in range(self.function.ndim - 1, -1, -1):
            upper = b.shape_index(i, self.function)
            body = b.for_range_upwards(body, upper=upper)
            self.indices.append(body.target)

        self.visitchildren(body)
        return body

    def visit_ForNode(self, node):
        if node.body.may_error(self.context):
            node.body = self.astbuilder.error_handler(node.body)
        self.visitchildren(node)
        return node

    def _element_location(self, node):
        b = self.astbuilder
        ndim = node.type.ndim
        indices = [b.mul(index, b.stride(node, i))
                   for i, index in enumerate(self.indices[-ndim:])]
        pointer = b.cast(b.data_pointer(node),
                         minitypes.c_char_t.pointer())
        node = b.index_multiple(pointer, indices,
                                dest_pointer_type=node.type.dtype.pointer())
        self.visitchildren(node)
        return node

    def visit_Variable(self, node):
        if node.name in self.function.args and node.type.is_array:
            return self._element_location(node)

        return super(StridedSpecializer, self).visit_Variable(node)

    def visit_ErrorHandler(self, node):
        b = self.astbuilder
        if self.error_handlers:
            node.error_variable = b.temp(minitypes.bool)
            node.error_var_init = b.assign(node.error_variable, 0)
            node.error_target_label = b.jump_target(node.error_label)
            node.error_set = b.assign(node.error_variable, 1)
            node.cascade = b.if_(node.error_variable,
                                 b.jump(self.error_handlers[-1].label))
        else:
            node.cascade = b.return_(self.function.error_value)

        self.error_handlers.append(node)
        self.visitchildren(node)
        self.error_handlers.pop()
        return node

class ContigSpecializer(StridedSpecializer):

    def visit_FunctionNode(self, node):
        b = self.astbuilder

        shapelist = node.shapevar
        shapevar = b.temp(node.shapevar.base_type.type)
        compute_shape = b.reduce(shapelist, b.mul, output=shapevar,
                                 length=b.constant(node.ndim))
        node.shapevar = shapevar
        node.body = node.stats(compute_shape, node.body)
        return super(ContigSpecializer, self).visit_FunctionNode(node)

    def visit_StridePointer(self, node):
        return None

    def visit_Variable(self, node):
        return super(ContigSpecializer, self).visit_Variable(node)