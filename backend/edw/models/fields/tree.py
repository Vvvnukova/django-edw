# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from mptt import fields


try:
    long_type = long
except NameError:
    long_type = int


class TreeForeignKey(fields.TreeForeignKey):
    """
    A foreignkey that limits the node types the parent can be.
    RUS: Внешний ключ отображает поля формы в виде дерева.
    Ограничивает типы узлов, у которых могут быть родители.
    """
    default_error_messages = {
        'no_children_allowed': _("The selected node cannot have child nodes."),
        'no_child_of_itself': _("A node may not be made a child of itself."),
        'unknown_parent_value': _("Unknown parent value.")
    }

    def clean(self, value, model_instance):
        """
        RUS: Возвращает проверенные данные, которые затем помещаются в словарь cleaned_data формы.
        """
        value = super(TreeForeignKey, self).clean(value, model_instance)
        self._validate_parent(value, model_instance)
        return value

    def _validate_parent(self, value, instance):
        """
        RUS: Проверка родителей. Родителем может быть объект, у которого значение равно первичному ключу,
        в противном случае возбуждается исключение.
        """
        if not value:
            return
        elif isinstance(value, (int, long_type)):
            model_class = instance.__class__
            try:
                parent = model_class._default_manager.get(pk=value)
            except model_class.DoesNotExist:
                raise ValueError(self.error_messages['unknown_parent_value'])
            if value == instance.pk:
                raise ValidationError(self.error_messages['no_child_of_itself'])
            if not parent.can_have_children:
                raise ValidationError(self.error_messages['no_children_allowed'])
        else:
            raise ValueError(self.error_messages['unknown_parent_value'])
