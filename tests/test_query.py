from collections import defaultdict
from datetime import date

import pytest
from django.db.models import (
    F,
    Q,
    QuerySet,
)
from iommi.page import perform_ajax_dispatch
from tri_declarative import class_shortcut
from tri_struct import Struct
from iommi.form import (
    Field,
    Form,
)
from iommi.query import (
    ADVANCED_QUERY_PARAM,
    FREETEXT_SEARCH_NAME,
    Q_OP_BY_OP,
    Query,
    QueryException,
    value_to_query_string_value_string,
    Variable,
)
from iommi.base import request_data

from tests.helpers import req
from tests.models import (
    Bar,
    EndPointDispatchModel,
    Foo,
    FromModelWithInheritanceTest,
    NonStandardName,
)


class MyTestQuery(Query):
    foo_name = Variable(attr='foo', freetext=True, gui__show=True)
    bar_name = Variable.case_sensitive(attr='bar', freetext=True, gui__show=True)
    baz_name = Variable(attr='baz')


# F/Q expressions don't have a __repr__ which makes testing properly impossible, so let's just monkey patch that in
def f_repr(self):
    return '<F: %s>' % self.name


F.__repr__ = f_repr
Q.__repr__ = lambda self: str(self)


def test_show():
    class ShowQuery(Query):
        foo = Variable()
        bar = Variable(
            show=lambda query, variable: query.request().GET['foo'] == 'show' and variable.extra.foo == 'show2',
            extra__foo='show2')

    # noinspection PyTypeChecker
    assert [x.name for x in ShowQuery(request=req('get', foo='hide')).bound_variables] == ['foo']

    # noinspection PyTypeChecker
    assert [x.name for x in ShowQuery(request=req('get', foo='show')).bound_variables] == ['foo', 'bar']


def test_request_data():
    r = Struct(method='POST', POST='POST', GET='GET')
    assert request_data(r) == 'POST'
    r.method = 'GET'
    assert request_data(r) == 'GET'


def test_empty_string():
    query = MyTestQuery()
    assert repr(query.parse('')) == repr(Q())


def test_unknown_field():
    query = MyTestQuery()
    with pytest.raises(QueryException) as e:
        query.parse('unknown_variable=1')

    assert 'Unknown variable "unknown_variable"' in str(e)
    assert isinstance(e.value, QueryException)


def test_freetext():
    query = MyTestQuery()
    expected = repr(Q(**{'foo__icontains': 'asd'}) | Q(**{'bar__contains': 'asd'}))
    assert repr(query.parse('"asd"')) == expected

    query2 = MyTestQuery(request=req('get', **{'-': '-', 'term': 'asd'}))
    assert repr(query2.to_q()) == expected


def test_or():
    query = MyTestQuery()
    assert repr(query.parse('foo_name="asd" or bar_name = 7')) == repr(Q(**{'foo__iexact': 'asd'}) | Q(**{'bar__exact': 7}))


def test_and():
    query = MyTestQuery()
    assert repr(query.parse('foo_name="asd" and bar_name = 7')) == repr(Q(**{'foo__iexact': 'asd'}) & Q(**{'bar__exact': 7}))


def test_negation():
    query = MyTestQuery()
    assert repr(query.parse('foo_name!:"asd" and bar_name != 7')) == repr(~Q(**{'foo__icontains': 'asd'}) & ~Q(**{'bar__exact': 7}))


def test_precedence():
    query = MyTestQuery()
    assert repr(query.parse('foo_name="asd" and bar_name = 7 or baz_name = 11')) == repr((Q(**{'foo__iexact': 'asd'}) & Q(**{'bar__exact': 7})) | Q(**{'baz__iexact': 11}))
    assert repr(query.parse('foo_name="asd" or bar_name = 7 and baz_name = 11')) == repr(Q(**{'foo__iexact': 'asd'}) | (Q(**{'bar__exact': 7})) & Q(**{'baz__iexact': 11}))


@pytest.mark.parametrize('op,django_op', [
    ('>', 'gt'),
    ('=>', 'gte'),
    ('>=', 'gte'),
    ('<', 'lt'),
    ('<=', 'lte'),
    ('=<', 'lte'),
    ('=', 'iexact'),
    (':', 'icontains'),
])
def test_ops(op, django_op):
    query = MyTestQuery()
    assert repr(query.parse('foo_name%sbar' % op)) == repr(Q(**{'foo__%s' % django_op: 'bar'}))


def test_parenthesis():
    query = MyTestQuery()
    assert repr(query.parse('foo_name="asd" and (bar_name = 7 or baz_name = 11)')) == repr(Q(**{'foo__iexact': 'asd'}) & (Q(**{'bar__exact': 7}) | Q(**{'baz__iexact': 11})))


def test_request_to_q_advanced():
    # noinspection PyTypeChecker
    query = MyTestQuery(request=req('get', **{ADVANCED_QUERY_PARAM: 'foo_name="asd" and (bar_name = 7 or baz_name = 11)'}))
    assert repr(query.to_q()) == repr(Q(**{'foo__iexact': 'asd'}) & (Q(**{'bar__exact': 7}) | Q(**{'baz__iexact': 11})))


def test_request_to_q_simple():
    class Query2(MyTestQuery):
        bazaar = Variable.boolean(attr='quux__bar__bazaar', gui__show=True)

    # noinspection PyTypeChecker
    query2 = Query2(request=req('get', **{'foo_name': "asd", 'bar_name': '7', 'bazaar': 'true'}))
    assert repr(query2.to_q()) == repr(Q(**{'foo__iexact': 'asd'}) & Q(**{'bar__exact': '7'}) & Q(**{'quux__bar__bazaar__iexact': 1}))

    # noinspection PyTypeChecker
    query2 = Query2(request=req('get', **{'foo_name': "asd", 'bar_name': '7', 'bazaar': 'false'}))
    assert repr(query2.to_q()) == repr(Q(**{'foo__iexact': 'asd'}) & Q(**{'bar__exact': '7'}) & Q(**{'quux__bar__bazaar__iexact': 0}))


def test_boolean_parse():
    class MyQuery(Query):
        foo = Variable.boolean()

    assert repr(MyQuery().parse('foo=false')) == repr(Q(**{'foo__iexact': False}))
    assert repr(MyQuery().parse('foo=true')) == repr(Q(**{'foo__iexact': True}))


def test_integer_request_to_q_simple():
    class Query2(Query):
        bazaar = Variable.integer(attr='quux__bar__bazaar', gui=Struct(show=True))

    # noinspection PyTypeChecker
    query2 = Query2(request=req('get', bazaar='11'))
    assert repr(query2.to_q()) == repr(Q(**{'quux__bar__bazaar__iexact': 11}))


def test_gui_is_not_required():
    class Query2(Query):
        foo = Variable()
    assert Query2.foo.gui.required is False


def test_invalid_value():
    request = req('get', query='bazaar=asd')
    # noinspection PyTypeChecker
    query2 = Query(request=request, variables=[Variable.integer(name='bazaar', value_to_q=lambda variable, op, value_string_or_f: None)])
    with pytest.raises(QueryException) as e:
        query2.to_q()
    assert 'Unknown value "asd" for variable "bazaar"' in str(e)


def test_invalid_variable():
    # noinspection PyTypeChecker
    query2 = Query(request=req('get', query='not_bazaar=asd'), variables=[Variable(name='bazaar')])
    with pytest.raises(QueryException) as e:
        query2.to_q()
    assert 'Unknown variable "not_bazaar"' in str(e)


def test_invalid_form_data():
    # noinspection PyTypeChecker
    query2 = Query(request=req('get', bazaar='asds'), variables=[Variable.integer(name='bazaar', attr='quux__bar__bazaar', gui__show=True)])
    assert query2.to_query_string() == ''
    assert repr(query2.to_q()) == repr(Q())


def test_none_attr():
    # noinspection PyTypeChecker
    query2 = Query(request=req('get', bazaar='foo'), variables=[Variable(name='bazaar', attr=None, gui__show=True)])
    assert repr(query2.to_q()) == repr(Q())


def test_request_to_q_freetext():
    # noinspection PyTypeChecker
    query = MyTestQuery(request=req('get', **{FREETEXT_SEARCH_NAME: "asd"}))
    assert repr(query.to_q()) == repr(Q(**{'foo__icontains': 'asd'}) | Q(**{'bar__contains': 'asd'}))


def test_self_reference_with_f_object():
    query = MyTestQuery()
    assert repr(query.parse('foo_name=bar_name')) == repr(Q(**{'foo__iexact': F('bar')}))


def test_null():
    query = MyTestQuery()
    assert repr(query.parse('foo_name=null')) == repr(Q(**{'foo': None}))


def test_date():
    query = MyTestQuery()
    assert repr(query.parse('foo_name=2014-03-07')) == repr(Q(**{'foo__iexact': date(2014, 3, 7)}))


def test_date_out_of_range():
    query = MyTestQuery()
    with pytest.raises(QueryException) as e:
        query.parse('foo_name=2014-03-37')

    assert 'out of range' in str(e)


def test_invalid_syntax():
    query = MyTestQuery()
    with pytest.raises(QueryException) as e:
        query.parse('asdadad213124av@$#$#')

    assert 'Invalid syntax for query' in str(e)


@pytest.mark.django_db
def test_choice_queryset():
    foos = [Foo.objects.create(foo=5), Foo.objects.create(foo=7)]

    # make sure we get either 1 or 3 objects later when we choose a random pk
    Bar.objects.create(foo=foos[0])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])

    class Query2(Query):
        foo = Variable.choice_queryset(
            choices=Foo.objects.all(),
            gui__show=True,
            value_to_q_lookup='foo')
        baz = Variable.choice_queryset(
            model=Foo,
            attr=None,
            choices=None,
        )

    random_valid_obj = Foo.objects.all().order_by('?')[0]

    # test GUI
    form = Query2(request=req('post', **{'-': '-', 'foo': 'asdasdasdasd'})).form
    assert not form.is_valid()
    query2 = Query2(request=req('post', **{'-': '-', 'foo': str(random_valid_obj.pk)}))
    form = query2.form
    assert form.is_valid()
    assert set(form.fields_by_name['foo'].choices) == set(Foo.objects.all())
    q = query2.to_q()
    assert set(Bar.objects.filter(q)) == set(Bar.objects.filter(foo__pk=random_valid_obj.pk))

    # test query
    query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo=%s and baz=buzz' % str(random_valid_obj.foo)}))
    q = query2.to_q()
    assert set(Bar.objects.filter(q)) == set(Bar.objects.filter(foo__pk=random_valid_obj.pk))
    assert repr(q) == repr(Q(**{'foo__pk': random_valid_obj.pk}))

    # test searching for something that does not exist
    query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo=%s' % str(11)}))
    value_that_does_not_exist = 11
    assert Foo.objects.filter(foo=value_that_does_not_exist).count() == 0
    with pytest.raises(QueryException) as e:
        query2.to_q()
    assert ('Unknown value "%s" for variable "foo"' % value_that_does_not_exist) in str(e)

    # test invalid ops
    valid_ops = ['=']
    for invalid_op in [op for op in Q_OP_BY_OP.keys() if op not in valid_ops]:
        query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo%s%s' % (invalid_op, str(random_valid_obj.foo))}))
        with pytest.raises(QueryException) as e:
            query2.to_q()
        assert('Invalid operator "%s" for variable "foo"' % invalid_op) in str(e)

    # test a string with the contents "null"
    assert repr(query2.parse('foo="null"')) == repr(Q(foo=None))


@pytest.mark.django_db
def test_multi_choice_queryset():
    foos = [Foo.objects.create(foo=5), Foo.objects.create(foo=7)]

    # make sure we get either 1 or 3 objects later when we choose a random pk
    Bar.objects.create(foo=foos[0])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])
    Bar.objects.create(foo=foos[1])

    class Query2(Query):
        foo = Variable.multi_choice_queryset(
            choices=Foo.objects.all(),
            gui__show=True,
            value_to_q_lookup='foo')
        baz = Variable.multi_choice_queryset(
            model=Foo,
            attr=None,
            choices=None,
        )

    random_valid_obj, random_valid_obj2 = Foo.objects.all().order_by('?')[:2]

    # test GUI
    form = Query2(request=req('post', **{'-': '-', 'foo': 'asdasdasdasd'})).form
    assert not form.is_valid()
    query2 = Query2(request=req('post', **{'-': '-', 'foo': [str(random_valid_obj.pk), str(random_valid_obj2.pk)]}))
    form = query2.form
    assert form.is_valid()
    assert set(form.fields_by_name['foo'].choices) == set(Foo.objects.all())
    q = query2.to_q()
    assert set(Bar.objects.filter(q)) == set(Bar.objects.filter(foo__pk__in=[random_valid_obj.pk, random_valid_obj2.pk]))

    # test query
    query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo=%s and baz=buzz' % str(random_valid_obj.foo)}))
    q = query2.to_q()
    assert set(Bar.objects.filter(q)) == set(Bar.objects.filter(foo__pk=random_valid_obj.pk))
    assert repr(q) == repr(Q(**{'foo__pk': random_valid_obj.pk}))

    # test searching for something that does not exist
    query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo=%s' % str(11)}))
    value_that_does_not_exist = 11
    assert Foo.objects.filter(foo=value_that_does_not_exist).count() == 0
    with pytest.raises(QueryException) as e:
        query2.to_q()
    assert ('Unknown value "%s" for variable "foo"' % value_that_does_not_exist) in str(e)

    # test invalid ops
    valid_ops = ['=']
    for invalid_op in [op for op in Q_OP_BY_OP.keys() if op not in valid_ops]:
        query2 = Query2(request=req('post', **{'-': '-', 'query': 'foo%s%s' % (invalid_op, str(random_valid_obj.foo))}))
        with pytest.raises(QueryException) as e:
            query2.to_q()
        assert('Invalid operator "%s" for variable "foo"' % invalid_op) in str(e)


@pytest.mark.django_db
def test_from_model_with_model_class():
    t = Query.from_model(model=Foo)
    assert [x.name for x in t.variables] == ['id', 'foo']
    assert [x.name for x in t.variables if x.show] == ['foo']


@pytest.mark.django_db
def test_from_model_with_queryset():
    t = Query.from_model(rows=Foo.objects.all())
    assert [x.name for x in t.variables] == ['id', 'foo']
    assert [x.name for x in t.variables if x.show] == ['foo']


def test_from_model_foreign_key():
    class MyQuery(Query):
        class Meta:
            variables = Query.variables_from_model(model=Bar)

    t = MyQuery(request=req('get'))
    assert [x.name for x in t.variables] == ['id', 'foo']
    assert isinstance(t.bound_variable_by_name['foo'].choices, QuerySet)


@pytest.mark.django_db
def test_endpoint_dispatch():
    EndPointDispatchModel.objects.create(name='foo')
    x = EndPointDispatchModel.objects.create(name='bar')

    class MyQuery(Query):
        foo = Variable.choice_queryset(
            gui__show=True,
            gui__attr='name',
            choices=EndPointDispatchModel.objects.all().order_by('id'),
        )

    request = req('get')
    query = MyQuery(request=request)

    assert '/foo' == query.form.fields_by_name.foo.endpoint_path()
    expected = {
        'more': False,
        'page': 1,
        'results': [{'id': x.pk, 'text': str(x)}],
    }
    assert perform_ajax_dispatch(root=query, path='/gui/field/foo', value='ar', request=request) == expected
    assert perform_ajax_dispatch(root=query, path='/foo', value='ar', request=request) == expected


def test_endpoint_dispatch_errors():
    class MyQuery(Query):
        foo = Variable.choice(
            gui__show=True,
            gui__attr='name',
            choices=('a', 'b'),
        )

    assert perform_ajax_dispatch(root=MyQuery(), path='/errors', value='', request=req('get', **{ADVANCED_QUERY_PARAM: 'foo=!'})) == {'global': ['Invalid syntax for query']}
    assert perform_ajax_dispatch(root=MyQuery(), path='/errors', value='', request=req('get', **{ADVANCED_QUERY_PARAM: 'foo=a'})) == {}
    assert perform_ajax_dispatch(root=MyQuery(), path='/errors', value='', request=req('get', foo='q')) == {'fields': {'foo': ['q not in available choices']}}


def test_variable_repr():
    assert repr(Variable(name='foo')) == '<iommi.query.Variable foo>'


@pytest.mark.django_db
def test_nice_error_message():
    with pytest.raises(AttributeError) as e:
        value_to_query_string_value_string(Variable(value_to_q_lookup='name'), NonStandardName(non_standard_name='foo'))

    assert str(e.value) == "<class 'tests.models.NonStandardName'> object has no attribute name. You can specify another name property with the value_to_q_lookup argument. Maybe one of ['non_standard_name']?"

    with pytest.raises(AttributeError) as e:
        value_to_query_string_value_string(Variable(value_to_q_lookup='name'), Foo(foo=5))

    assert str(e.value) == "<class 'tests.models.Foo'> object has no attribute name. You can specify another name property with the value_to_q_lookup argument."


def test_escape_quote():
    class MyQuery(Query):
        foo = Variable(gui__show=True)

    # noinspection PyTypeChecker
    query = MyQuery(request=Struct(method='GET', GET={'foo': '"', '-': '-'}))
    assert query.to_query_string() == 'foo="\\""'
    assert repr(query.to_q()) == repr(Q(**{'foo__iexact': '"'}))


def test_escape_quote_freetext():
    class MyQuery(Query):
        foo = Variable(freetext=True)

    # noinspection PyTypeChecker
    query = MyQuery(request=Struct(method='GET', GET={'term': '"', '-': '-'}))
    assert query.to_query_string() == '(foo:"\\"")'
    assert repr(query.to_q()) == repr(Q(**{'foo__icontains': '"'}))


def test_freetext_combined_with_other_stuff():
    class MyTestQuery(Query):
        foo_name = Variable(attr='foo', freetext=True, gui__show=True)
        bar_name = Variable.case_sensitive(attr='bar', freetext=True, gui__show=True)

        baz_name = Variable(attr='baz', gui__show=True)

    expected = repr(Q(**{'baz__iexact': '123'}) & Q(Q(**{'foo__icontains': 'asd'}) | Q(**{'bar__contains': 'asd'})))

    assert repr(MyTestQuery(request=req('get', **{'-': '-', 'term': 'asd', 'baz_name': '123'})).to_q()) == expected


@pytest.mark.django_db
def test_from_model_with_inheritance():
    was_called = defaultdict(int)

    class MyField(Field):
        @classmethod
        @class_shortcut
        def float(cls, call_target=None, **kwargs):
            was_called['MyField.float'] += 1
            return call_target(**kwargs)

    class MyForm(Form):
        class Meta:
            member_class = MyField

    class MyVariable(Variable):
        @classmethod
        @class_shortcut(
            gui__call_target__attribute='float',
        )
        def float(cls, call_target=None, **kwargs):
            was_called['MyVariable.float'] += 1
            return call_target(**kwargs)

    class MyQuery(Query):
        class Meta:
            member_class = MyVariable
            form_class = MyForm

    query = MyQuery.from_model(
        rows=FromModelWithInheritanceTest.objects.all(),
        model=FromModelWithInheritanceTest,
        variable__value__gui__show=True,
    )
    query.bind(request=req('get'))

    assert was_called == {
        'MyField.float': 1,
        'MyVariable.float': 1,
    }
