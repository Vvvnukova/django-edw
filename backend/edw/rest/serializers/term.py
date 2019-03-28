# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django.core.cache import cache
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

from rest_framework import serializers
from rest_framework import exceptions
from rest_framework.generics import get_object_or_404
from rest_framework.compat import unicode_to_repr
from rest_framework.fields import empty

from rest_framework_recursive.fields import RecursiveField

from rest_framework_bulk.serializers import BulkListSerializer, BulkSerializerMixin

from edw.models.term import TermModel
from edw.models.data_mart import DataMartModel
from edw.rest.serializers.decorators import get_from_context_or_request, get_from_context


TERM_UPDATE_LOOKUP_FIELDS = ('id', 'slug')


class TermValidator(object):
    """
    Term Validator
    """
    def __init__(self, model):
        self.model = model

    def set_context(self, serializer):
        """
        This hook is called by the serializer instance,
        prior to the validation call being made.
        """
        # Determine the existing instance, if this is an update operation.
        self.instance = getattr(serializer, 'instance', None)

    def __call__(self, attrs):

        validated_data = dict(attrs)

        # todo: empty ???
        parent__slug = validated_data.pop('parent__slug', None)
        if self.instance is not None:
            exclude = TERM_UPDATE_LOOKUP_FIELDS
            if parent__slug is not None:
                try:
                    TermModel.objects.get(slug=parent__slug)
                except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                    raise exceptions.NotFound(e)
        else:
            exclude = ('path',)

        try:
            self.model(**validated_data).full_clean(exclude=exclude)
        except ObjectDoesNotExist as e:
            raise exceptions.NotFound(e)
        except ValidationError as e:
            raise serializers.ValidationError(e)

    def __repr__(self):
        return unicode_to_repr('<%s>' % (
            self.__class__.__name__
        ))


class TermSerializer(BulkSerializerMixin, serializers.ModelSerializer):
    """
    A simple serializer to convert the terms data for rendering.
    """
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True, required=False)
    slug = serializers.SlugField(max_length=50, min_length=None, allow_blank=False)
    path = serializers.CharField(max_length=255, allow_blank=False, read_only=True)
    semantic_rule = serializers.ChoiceField(choices=TermModel.SEMANTIC_RULES, required=False)
    specification_mode = serializers.ChoiceField(choices=TermModel.SPECIFICATION_MODES, required=False)
    active = serializers.BooleanField(required=False, default=True)
    description = serializers.CharField(read_only=True)
    is_leaf = serializers.SerializerMethodField()
    short_description = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    parent__slug = serializers.SlugField(max_length=50, min_length=None, allow_blank=True, write_only=True,
                                         required=False)

    class Meta:
        model = TermModel
        list_serializer_class = BulkListSerializer

        # todo: update_lookup_fields --> lookup_fields
        update_lookup_fields = TERM_UPDATE_LOOKUP_FIELDS
        validators = [TermValidator(model)]

    def _prepare_validated_data(self, validated_data):

        parent__slug = validated_data.pop('parent__slug', None)
        if parent__slug is not None:
            try:
                parent = TermModel.objects.get(slug=parent__slug)
            except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                raise exceptions.NotFound(e)
            else:
                validated_data['parent_id'] = parent.id

        return validated_data

    def create(self, validated_data):

        validated_data = self._prepare_validated_data(validated_data)

        for id_attr in self.Meta.update_lookup_fields:

            id_value = validated_data.pop(id_attr, empty)

            if id_value != empty:

                result, created = TermModel.objects.update_or_create(**{
                    id_attr: id_value,
                    'defaults': validated_data
                })
                # todo: multiple ???

                break
        else:
            raise ValidationError('')

        return result

    def update(self, instance, validated_data):

        validated_data = self._prepare_validated_data(validated_data)

        result = super(TermSerializer, self).update(instance, validated_data)

        return result

    def get_is_leaf(self, instance):
        return instance.is_leaf_node()

    def get_short_description(self, instance):
        if not instance.description:
            return ''
        return mark_safe(
            Truncator(Truncator(instance.description).words(10, truncate=" ...")).chars(80, truncate="..."))

    def get_url(self, instance):
        return instance.get_absolute_url(request=self.context.get('request'), format=self.context.get('format'))


class TermDetailSerializer(TermSerializer):
    '''
    TermDetailSerializer
    '''
    class Meta(TermSerializer.Meta):
        fields = ('id', 'parent_id', 'name', 'slug', 'path', 'semantic_rule', 'specification_mode', 'url', 'active',
                  'description', 'view_class', 'created_at', 'updated_at', 'level', 'attributes', 'is_leaf',
                  'parent__slug')


class TermSummarySerializer(TermSerializer):
    '''
    TermSummarySerializer
    '''
    class Meta(TermSerializer.Meta):
        fields = ('id', 'parent_id', 'name', 'slug', 'semantic_rule', 'specification_mode', 'url', 'active',
                  'view_class', 'attributes', 'is_leaf', 'short_description')


class _TermsFilterMixin(object):
    '''
    If `active_only` parameter set `True`, then add filtering by `active` = `True`
    '''
    @cached_property
    @get_from_context_or_request('active_only', True)
    def is_active_only(self, value):
        '''
        :return: `active_only` value in context or request, default: True
        '''
        return serializers.BooleanField().to_internal_value(value)

    def active_only_filter(self, data):
        if self.is_active_only:
            return data.active()
        else:
            return data

    def get_selected_terms(self):
        '''
        :return: `None` if parent node not selected, or selected child dict
        '''
        raise NotImplementedError(
            '{cls}.get_selected_terms() must be implemented.'.format(
                cls=self.__class__.__name__
            )
        )

    @property
    def is_expanded_specification(self):
        '''
        :return: `True` if parent node specification mode is `expanded`
        '''
        raise NotImplementedError(
            '{cls}.is_expanded_specification must be implemented.'.format(
                cls=self.__class__.__name__
            )
        )

    @cached_property
    @get_from_context_or_request('max_depth', None)
    def max_depth(self, value):
        '''
        :return: `max_depth` value in context or request, default: None
        '''
        return serializers.IntegerField().to_internal_value(value)

    @property
    def depth(self):
        '''
        :return: recursion depth
        '''
        raise NotImplementedError(
            '{cls}.depth must be implemented.'.format(
                cls=self.__class__.__name__
            )
        )

    @cached_property
    @get_from_context_or_request('cached', True)
    def cached(self, value):
        '''
        :return: `cached` value in context or request, default: True
        '''
        return serializers.BooleanField().to_internal_value(value)

    @staticmethod
    def on_cache_set(key):
        buf = TermModel.get_children_buffer()
        old_key = buf.record(key)
        if old_key != buf.empty:
            cache.delete(old_key)

    def prepare_data(self, data):
        if self.cached:
            return data.cache(on_cache_set=_TermsFilterMixin.on_cache_set, timeout=TermModel.CHILDREN_CACHE_TIMEOUT)
        else:
            return data.prepare_for_cache(data)

    def to_representation(self, data):
        next_depth = self.depth + 1
        if self.max_depth is not None and next_depth > self.max_depth:
            terms = []
        else:
            selected_terms = self.get_selected_terms()
            if self.is_expanded_specification or selected_terms is not None:
                terms = self.prepare_data(self.active_only_filter(data))
                for term in terms:
                    term._depth = next_depth
                    try:
                        term._selected_term_info = selected_terms.pop(term.id)
                    except (KeyError, AttributeError):
                        term._selected_term_info = None
            else:
                terms = []
        return super(_TermsFilterMixin, self).to_representation(terms)


class TermTreeListField(_TermsFilterMixin, serializers.ListField):
    """
    TermTreeListField
    """
    def get_selected_terms(self):
        term_info = self.parent._selected_term_info
        return None if term_info is None else term_info.get_children_dict()

    @property
    def is_expanded_specification(self):
        return self.parent._is_expanded_specification

    @property
    def depth(self):
        return self.parent._depth


class _TermTreeRootSerializer(_TermsFilterMixin, serializers.ListSerializer):
    """
    Term Tree Root Serializer
    """
    def get_selected_terms(self):
        selected = self.selected[:]
        has_selected = bool(selected)

        if self.data_mart:
            trunk = list(self.active_only_filter(self.data_mart.terms.values_list('id', flat=True)))
            selected.extend(trunk)
        else:
            trunk = selected

        decompress = TermModel.cached_decompress if self.cached else TermModel.decompress

        trunk = decompress(trunk, self.fix_it)
        if has_selected:
            tree = decompress(selected, self.fix_it)
        else:
            tree = trunk

        for k, v in trunk.items():
            x = tree.get(k)
            if x is not None:
                if v.is_leaf:
                    x.attrs['structure'] = 'limb'
                else:
                    x.attrs['structure'] = 'trunk'

        root_pk = self.context.get('root_pk', None)
        root = tree.pop(root_pk, tree.root)

        return root.get_children_dict()

    @property
    def is_expanded_specification(self):
        return True

    @cached_property
    @get_from_context_or_request('fix_it', True)
    def fix_it(self, value):
        '''
        :return: `fix_it` value in context or request, default: True
        '''
        return serializers.BooleanField().to_internal_value(value)

    @cached_property
    @get_from_context_or_request('selected', [])
    def selected(self, value):
        '''
        :return: `selected` terms ids in context or request, default: []
        '''
        return serializers.ListField(child=serializers.IntegerField()).to_internal_value(value.split(",")) if value else []

    @cached_property
    @get_from_context('data_mart')
    def data_mart(self):
        '''
        :return: active `DataMartModel` instance from context, if `data_mart` not set, try find object by parsing request
        '''
        def get_queryset():
            return DataMartModel.objects.active()
        pk = self.data_mart_pk
        if pk is not None:
            return get_object_or_404(get_queryset(), pk=pk)
        else:
            path = self.data_mart_path
            if path is not None:
                return get_object_or_404(get_queryset(), path=path)
        return None

    @cached_property
    @get_from_context_or_request('data_mart_pk', None)
    def data_mart_pk(self, value):
        '''
        :return: `data_mart_pk` data mart id in context or request, default: None
        '''
        return serializers.IntegerField().to_internal_value(value)

    @cached_property
    @get_from_context_or_request('data_mart_path', None)
    def data_mart_path(self, value):
        '''
        :return: `data_mart_path` data mart path in context or request, default: None
        '''
        return serializers.CharField().to_internal_value(value)

    @property
    def depth(self):
        return 0


class TermTreeSerializer(TermSerializer):
    """
    Term Tree Serializer
    """
    children = TermTreeListField(child=RecursiveField(), source='get_children', read_only=True)
    structure = serializers.SerializerMethodField()

    class Meta(TermSerializer.Meta):
        fields = ('id', 'name', 'slug', 'semantic_rule', 'specification_mode', 'url', 'active',
                  'attributes', 'is_leaf', 'view_class', 'structure', 'short_description', 'children')
        list_serializer_class = _TermTreeRootSerializer

    def to_representation(self, data):
        """
        Prepare some data for children serialization
        """
        self._depth = data._depth
        self._selected_term_info = data._selected_term_info
        self._is_expanded_specification = data.specification_mode == TermModel.EXPANDED_SPECIFICATION
        return super(TermSerializer, self).to_representation(data)

    def get_structure(self, instance):
        if self._selected_term_info is not None:
            return self._selected_term_info.attrs.get('structure', 'branch')
        return None  # 'twig', node not selected
