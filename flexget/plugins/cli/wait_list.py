from __future__ import unicode_literals, division, absolute_import
from builtins import *  # pylint: disable=unused-import, redefined-builtin

from argparse import ArgumentParser, ArgumentTypeError
from functools import partial

from colorclass.toggles import disable_all_colors
from flexget import options
from flexget.event import event
from flexget.manager import Session
from flexget.plugins.list.wait_list import get_wait_entry_by_id, get_wait_entry_by_title, WaitListList, WaitListEntry
from flexget.plugins.list.wait_list import get_wait_lists, get_list_by_exact_name, get_wait_entries_by_list_id
from flexget.terminal import TerminalTable, TerminalTableError, table_parser, console, colorize
from sqlalchemy.orm.exc import NoResultFound


def attribute_type(attribute):
    if attribute.count('=') != 1:
        raise ArgumentTypeError('Received attribute in wrong format: %s, '
                                'should be in keyword format like `imdb_id=tt1234567`' % attribute)
    name, value = attribute.split('=', 2)
    return {name: value}


def do_cli(manager, options):
    """Handle entry-list subcommand"""

    if hasattr(options, 'table_type') and options.table_type == 'porcelain':
        disable_all_colors()

    action_map = {
        'all': wait_list_lists,
        'list': wait_list_list,
        'show': wait_list_show,
        'approve': partial(wait_list_approve, approve=True),
        'reject': partial(wait_list_approve, approve=False),
        'del': wait_list_del,
        'add': wait_list_add,
        'purge': wait_list_purge
    }

    action_map[options.list_action](options)


def wait_list_lists(options):
    """ Show all wait lists """
    with Session() as session:
        lists = get_wait_lists(session=session)
        header = ['#', 'List Name']
        table_data = [header]
        for entry_list in lists:
            table_data.append([entry_list.id, entry_list.name])
    table = TerminalTable(options.table_type, table_data)
    try:
        console(table.output)
    except TerminalTableError as e:
        console('ERROR: %s' % str(e))


def wait_list_list(options):
    """List wait entry list"""
    with Session() as session:
        try:
            wait_list = get_list_by_exact_name(options.list_name, session=session)
        except NoResultFound:
            console('Could not find wait list with name {}'.format(options.list_name))
            return
        header = ['#', 'Title', '# of fields', 'Approved']
        table_data = [header]
        for entry in get_wait_entries_by_list_id(wait_list.id, order_by='added', descending=True, session=session):
            approved = colorize('green', entry.approved) if entry.approved else entry.approved
            table_data.append([entry.id, entry.title, len(entry.entry), approved])
    table = TerminalTable(options.table_type, table_data)
    try:
        console(table.output)
    except TerminalTableError as e:
        console('ERROR: %s' % str(e))


def wait_list_show(options):
    with Session() as session:
        try:
            wait_list = get_list_by_exact_name(options.list_name, session=session)
        except NoResultFound:
            console('Could not find wait list with name {}'.format(options.list_name))
            return

        try:
            entry = get_wait_entry_by_id(wait_list.id, int(options.entry), session=session)
        except NoResultFound:
            console(
                'Could not find matching wait entry with ID {} in list `{}`'.format(int(options.entry),
                                                                                    options.list_name))
            return
        except ValueError:
            entry = get_wait_entry_by_title(wait_list.id, options.entry, session=session)
            if not entry:
                console(
                    'Could not find matching wait entry with title `{}` in list `{}`'.format(options.entry,
                                                                                             options.list_name))
                return
        header = ['Field name', 'Value']
        table_data = [header]
        for k, v in sorted(entry.entry.items()):
            table_data.append([k, str(v)])
    table = TerminalTable(options.table_type, table_data, wrap_columns=[1])
    table.table.justify_columns[0] = 'center'
    try:
        console(table.output)
    except TerminalTableError as e:
        console('ERROR: %s' % str(e))


def wait_list_add(options):
    with Session() as session:
        try:
            wait_list = get_list_by_exact_name(options.list_name, session=session)
        except NoResultFound:
            console('Could not find a wait list with name `{}`, creating'.format(options.list_name))
            wait_list = WaitListList(name=options.list_name)
            session.add(wait_list)
        session.merge(wait_list)
        session.commit()
        title = options.entry_title
        entry = {'title': options.entry_title, 'url': options.url}
        db_entry = get_wait_entry_by_title(list_id=wait_list.id, title=title, session=session)
        if db_entry:
            console("Entry with the title `{}` already exist with list `{}`. Will replace identifiers if given".format(
                title, wait_list.name))
            output = 'Successfully updated entry `{}` to wait list `{}` '.format(title, wait_list.name)
        else:
            console("Adding entry with title `{}` to list `{}`".format(title, wait_list.name))
            db_entry = WaitListEntry(entry=entry, wait_list_id=wait_list.id)
            if options.approved:
                console('marking entry as approved')
                db_entry.approved = True
            session.add(db_entry)
            output = 'Successfully added entry `{}` to wait list `{}` '.format(title, wait_list.name)
        if options.attributes:
            console('Adding attributes to entry `{}`'.format(title))
            for identifier in options.attributes:
                for k, v in identifier.items():
                    entry[k] = v
            db_entry.entry = entry
        console(output)


def wait_list_approve(options, approve=None):
    with Session() as session:
        try:
            entry_list = get_list_by_exact_name(options.list_name)
        except NoResultFound:
            console('Could not find wait list with name `{}`'.format(options.list_name))
            return
        try:
            db_entry = get_wait_entry_by_id(entry_list.id, int(options.entry), session=session)
        except NoResultFound:
            console('Could not find matching wait entry with ID {} in list `{}`'.format(int(options.entry),
                                                                                        options.list_name))
            return
        except ValueError:
            db_entry = get_wait_entry_by_title(entry_list.id, options.entry, session=session)
            if not db_entry:
                console('Could not find matching wait entry with title `{}` in list `{}`'.format(options.entry,
                                                                                                 options.list_name))
                return
        approve_text = 'approved' if approve else 'rejected'
        if (db_entry.approved is True and approve is True) or (db_entry.approved is False and approve is False):
            console('entry {} is already {}'.format(db_entry.title, approve_text))
            return
        db_entry.approved = approve
        console('Successfully marked pending entry {} as {}'.format(db_entry.title, approve_text))


def wait_list_del(options):
    with Session() as session:
        try:
            entry_list = get_list_by_exact_name(options.list_name)
        except NoResultFound:
            console('Could not find wait list with name `{}`'.format(options.list_name))
            return
        try:
            db_entry = get_wait_entry_by_id(entry_list.id, int(options.entry), session=session)
        except NoResultFound:
            console(
                'Could not find matching wait entry with ID {} in list `{}`'.format(int(options.entry),
                                                                                    options.list_name))
            return
        except ValueError:
            db_entry = get_wait_entry_by_title(entry_list.id, options.entry, session=session)
            if not db_entry:
                console(
                    'Could not find matching wait entry with title `{}` in list `{}`'.format(options.entry,
                                                                                             options.list_name))
                return
        console('Removing wait entry `{}` from list {}'.format(db_entry.title, options.list_name))
        session.delete(db_entry)


def wait_list_purge(options):
    with Session() as session:
        try:
            entry_list = get_list_by_exact_name(options.list_name)
        except NoResultFound:
            console('Could not find entry list with name `{}`'.format(options.list_name))
            return
        console('Deleting list {}'.format(options.list_name))
        session.delete(entry_list)


@event('options.register')
def register_parser_arguments():
    # Common option to be used in multiple subparsers
    entry_parser = ArgumentParser(add_help=False)
    entry_parser.add_argument('entry_title', help="Title of the entry")
    entry_parser.add_argument('url', help="URL of the entry")

    global_entry_parser = ArgumentParser(add_help=False)
    global_entry_parser.add_argument('entry', help='Can be entry title or ID')

    attributes_parser = ArgumentParser(add_help=False)
    attributes_parser.add_argument('--attributes', metavar='<attributes>', nargs='+', type=attribute_type,
                                   help='Can be a string or a list of string with the format imdb_id=XXX,'
                                        ' tmdb_id=XXX, etc')
    list_name_parser = ArgumentParser(add_help=False)
    list_name_parser.add_argument('list_name', nargs='?', default='wait_entries',
                                  help='Name of wait list to operate on')
    # Register subcommand
    parser = options.register_command('wait-list', do_cli, help='View and manage wait lists')
    # Set up our subparsers
    subparsers = parser.add_subparsers(title='actions', metavar='<action>', dest='list_action')
    subparsers.add_parser('all', help='Shows all existing wait lists', parents=[table_parser])
    subparsers.add_parser('list', parents=[list_name_parser, table_parser],
                          help='List pending entries from a wait list')
    subparsers.add_parser('show', parents=[list_name_parser, global_entry_parser, table_parser],
                          help='Show entry fields.')
    add = subparsers.add_parser('add', parents=[list_name_parser, entry_parser, attributes_parser],
                                help='Add a pending entry to a wait list')
    add.add_argument('--approved', action='store_true', help='Add an entry as approved')
    subparsers.add_parser('approve', parents=[list_name_parser, global_entry_parser],
                          help="Mark a pending entry as approved")
    subparsers.add_parser('reject', parents=[list_name_parser, global_entry_parser],
                          help="Mark a pending entry as rejected")
    subparsers.add_parser('del', parents=[list_name_parser, global_entry_parser],
                          help='Remove a pending entry from a wait list using its title or ID')
    subparsers.add_parser('purge', parents=[list_name_parser],
                          help='Removes an entire wait list with all of its entries. Use this with caution')