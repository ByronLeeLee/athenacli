from __future__ import print_function
from __future__ import unicode_literals
import logging
from re import compile, escape
from collections import Counter

from prompt_toolkit.completion import Completer, Completion

from .packages.completion_engine import suggest_type
from .packages.parseutils import last_word
from .packages.filepaths import parse_path, complete_path, suggest_path

_logger = logging.getLogger(__name__)


class AthenaCompleter(Completer):
    keywords = ['ACCESS', 'ADD', 'ALL', 'ALTER TABLE', 'AND', 'ANY', 'AS',
                'ASC', 'AUTO_INCREMENT', 'BEFORE', 'BEGIN', 'BETWEEN', 'BINARY', 'BY',
                'CASE', 'CHAR', 'CHECK', 'COLUMN', 'COMMENT', 'COMMIT', 'CONSTRAINT',
                'CHANGE MASTER TO', 'CHARACTER SET', 'COLLATE', 'CREATE', 'CURRENT', 'CURRENT_TIMESTAMP', 'DATABASE', 'DATE',
                'DECIMAL', 'DEFAULT', 'DELETE FROM', 'DELIMITER', 'DESC',
                'DESCRIBE', 'DROP', 'ELSE', 'END', 'ENGINE', 'ESCAPE', 'EXISTS',
                'FILE', 'FLOAT', 'FOR', 'FOREIGN KEY', 'FORMAT', 'FROM', 'FULL', 'FUNCTION', 'GRANT',
                'GROUP BY', 'HAVING', 'HOST', 'IDENTIFIED', 'IN', 'INCREMENT', 'INDEX',
                'INSERT INTO', 'INTEGER', 'INTO', 'INTERVAL', 'IS', 'JOIN', 'KEY', 'LEFT',
                'LEVEL', 'LIKE', 'LIMIT', 'LOCK', 'LOGS', 'LONG', 'MASTER', 'MODE',
                'MODIFY', 'NOT', 'NULL', 'NUMBER', 'OFFSET', 'ON', 'OPTION', 'OR',
                'ORDER BY', 'OUTER', 'OWNER', 'PASSWORD', 'PORT', 'PRIMARY',
                'PRIVILEGES', 'PROCESSLIST', 'PURGE', 'REFERENCES', 'REGEXP', 'RENAME', 'REPAIR', 'RESET',
                'REVOKE', 'RIGHT', 'ROLLBACK','ROW', 'ROWS', 'ROW_FORMAT', 'SELECT', 'SESSION', 'SET',
                'SHARE', 'SHOW', 'SLAVE', 'SMALLINT', 'START', 'STOP', 'TABLE', 'THEN',
                'TO', 'TRANSACTION', 'TRIGGER', 'TRUNCATE', 'UNION', 'UNIQUE', 'UNSIGNED', 'UPDATE',
                'USE', 'USER', 'USING', 'VALUES', 'VARCHAR', 'VIEW', 'WHEN', 'WHERE',
                'WITH']

    functions = ['AVG', 'CONCAT', 'COUNT', 'DISTINCT', 'FIRST', 'FORMAT', 'LAST',
                 'LCASE', 'LEN', 'MAX', 'MIN', 'MID', 'NOW', 'ROUND', 'SUM',
                 'TOP', 'UCASE']

    show_items = ['TABLES', 'DATABASES', 'SCHEMAS', 'PARTITIONS']

    users = []

    def __init__(self, smart_completion=True, supported_formats=(), keyword_casing='upper'):
        super(self.__class__, self).__init__()
        self.smart_completion = smart_completion
        self.reserved_words = set()
        for x in self.keywords:
            self.reserved_words.update(x.split())
        self.name_pattern = compile("^[_a-z][_a-z0-9\$]*$")

        self.special_commands = []
        self.table_formats = supported_formats
        if keyword_casing not in ('upper', 'lower', 'auto'):
            keyword_casing = 'auto'
        self.keyword_casing = keyword_casing
        self.reset_completions()

    def escape_name(self, name):
        if name and ((not self.name_pattern.match(name))
                or (name.upper() in self.reserved_words)
                or (name.upper() in self.functions)):
                    name = '`%s`' % name

        return name

    def unescape_name(self, name):
        """Unquote a string."""
        if name and name[0] == '"' and name[-1] == '"':
            name = name[1:-1]

        return name

    def escaped_names(self, names):
        return [self.escape_name(name) for name in names]

    def extend_special_commands(self, special_commands):
        # Special commands are not part of all_completions since they can only
        # be at the beginning of a line.
        self.special_commands.extend(special_commands)

    def extend_database_names(self, databases):
        self.databases.extend(databases)

    def extend_keywords(self, additional_keywords):
        self.keywords.extend(additional_keywords)
        self.all_completions.update(additional_keywords)

    def extend_users(self, users):
        for user in users:
            self.users.extend(user)
            self.all_completions.update(user)

    def extend_schemata(self, schema):
        if schema is None:
            return
        metadata = self.dbmetadata['tables']
        metadata[schema] = {}

        # dbmetadata.values() are the 'tables' and 'functions' dicts
        for metadata in self.dbmetadata.values():
            metadata[schema] = {}
        self.all_completions.update(schema)

    def extend_relations(self, data, kind):
        """Extend metadata for tables or views
        :param data: list of (rel_name, ) tuples
        :param kind: either 'tables' or 'views'
        :return:
        """
        # 'data' is a generator object. It can throw an exception while being
        # consumed. This could happen if the user has launched the app without
        # specifying a database name. This exception must be handled to prevent
        # crashing.
        try:
            data = [self.escaped_names(d) for d in data]
        except Exception:
            data = []

        # dbmetadata['tables'][$schema_name][$table_name] should be a list of
        # column names. Default to an asterisk
        metadata = self.dbmetadata[kind]
        for relname in data:
            try:
                metadata[self.dbname][relname[0]] = ['*']
            except KeyError:
                _logger.error('%r %r listed in unrecognized schema %r',
                              kind, relname[0], self.dbname)
            self.all_completions.add(relname[0])

    def extend_columns(self, column_data, kind):
        """Extend column metadata
        :param column_data: list of (rel_name, column_name) tuples
        :param kind: either 'tables' or 'views'
        :return:
        """
        # 'column_data' is a generator object. It can throw an exception while
        # being consumed. This could happen if the user has launched the app
        # without specifying a database name. This exception must be handled to
        # prevent crashing.
        try:
            column_data = [self.escaped_names(d) for d in column_data]
        except Exception:
            column_data = []

        metadata = self.dbmetadata[kind]
        for relname, column in column_data:
            metadata[self.dbname][relname].append(column)
            self.all_completions.add(column)

    def extend_functions(self, func_data):
        # 'func_data' is a generator object. It can throw an exception while
        # being consumed. This could happen if the user has launched the app
        # without specifying a database name. This exception must be handled to
        # prevent crashing.
        try:
            func_data = [self.escaped_names(d) for d in func_data]
        except Exception:
            func_data = []

        # dbmetadata['functions'][$schema_name][$function_name] should return
        # function metadata.
        metadata = self.dbmetadata['functions']

        for func in func_data:
            metadata[self.dbname][func[0]] = None
            self.all_completions.add(func[0])

    def set_dbname(self, dbname):
        self.dbname = dbname

    def reset_completions(self):
        self.databases = []
        self.users = []
        self.dbname = ''
        self.dbmetadata = {'tables': {}, 'views': {}, 'functions': {}}
        self.all_completions = set(self.keywords + self.functions)

    @staticmethod
    def find_matches(text, collection, start_only=False, fuzzy=True, casing=None):
        """Find completion matches for the given text.
        Given the user's input text and a collection of available
        completions, find completions matching the last word of the
        text.
        If `start_only` is True, the text will match an available
        completion only at the beginning. Otherwise, a completion is
        considered a match if the text appears anywhere within it.
        yields prompt_toolkit Completion instances for any matches found
        in the collection of available completions.
        """
        last = last_word(text, include='most_punctuations')
        text = last.lower()

        completions = []

        if fuzzy:
            regex = '.*?'.join(map(escape, text))
            pat = compile('(%s)' % regex)
            for item in sorted(collection):
                r = pat.search(item.lower())
                if r:
                    completions.append((len(r.group()), r.start(), item))
        else:
            match_end_limit = len(text) if start_only else None
            for item in sorted(collection):
                match_point = item.lower().find(text, 0, match_end_limit)
                if match_point >= 0:
                    completions.append((len(text), match_point, item))

        if casing == 'auto':
            casing = 'lower' if last and last[-1].islower() else 'upper'

        def apply_case(kw):
            if casing == 'upper':
                return kw.upper()
            return kw.lower()

        return (Completion(z if casing is None else apply_case(z), -len(text))
                for x, y, z in sorted(completions))

    def get_completions(self, document, complete_event, smart_completion=None):
        word_before_cursor = document.get_word_before_cursor(WORD=True)
        if smart_completion is None:
            smart_completion = self.smart_completion

        # If smart_completion is off then match any word that starts with
        # 'word_before_cursor'.
        if not smart_completion:
            return self.find_matches(word_before_cursor, self.all_completions,
                                     start_only=True, fuzzy=False)

        completions = []
        suggestions = suggest_type(document.text, document.text_before_cursor)

        for suggestion in suggestions:
            _logger.debug('Suggestion type: %r', suggestion['type'])
            # Map suggestion type to method
            # e.g. 'table' -> self.get_table_matches
            matcher = self.suggestion_matchers[suggestion['type']]
            completions.extend(matcher(self, suggestion, word_before_cursor))

        return completions

    def get_column_matches(self, suggestion, word_before_cursor):
        tables = suggestion['tables']
        _logger.debug('Completion column scope: %r', tables)
        scoped_cols = self.populate_scoped_cols(tables)
        if suggestion.get('drop_unique'):
            # drop_unique is used for 'tb11 JOIN tbl2 USING (...'
            # which should suggest only columns that appear in more than
            # one table
            scoped_cols = [
                col for (col, count) in Counter(scoped_cols).items()
                if count > 1 and col != '*'
            ]

        return self.find_matches(word_before_cursor, scoped_cols)

    def get_function_matches(self, suggestion, word_before_cursor):
        # suggest user-defined functions using substring matching
        funcs = self.populate_schema_objects(suggestion['schema'], 'functions')
        user_funcs = set(self.find_matches(word_before_cursor, funcs))

        # suggest hardcoded functions using startswith matching only if
        # there is no schema qualifier. If a schema qualifier is
        # present it probably denotes a table.
        # eg: SELECT * FROM users u WHERE u.
        if not suggestion['schema']:
            predefined_funcs = self.find_matches(
                word_before_cursor,
                self.functions,
                start_only=True,
                fuzzy=False,
                casing=self.keyword_casing
            )
            return user_funcs | set(predefined_funcs)

        return user_funcs

    def get_table_matches(self, suggestion, word_before_cursor):
        tables = self.populate_schema_objects(suggestion['schema'], 'tables')
        return self.find_matches(word_before_cursor, tables)

    def get_view_matches(self, suggestion, word_before_cursor):
        views = self.populate_schema_objects(suggestion['schema'], 'views')
        return self.find_matches(word_before_cursor, views)

    def get_alias_matches(self, suggestion, word_before_cursor):
        aliases = suggestion['aliases']
        return self.find_matches(word_before_cursor, aliases)

    def get_database_matches(self, _, word_before_cursor):
        return self.find_matches(word_before_cursor, self.databases)

    def get_schema_matches(self, _, word_before_cursor):
        # TODO
        return set()

    def get_keyword_matches(self, _, word_before_cursor):
        return self.find_matches(
            word_before_cursor,
            self.keywords,
            start_only=True,
            fuzzy=False,
            casing=self.keyword_casing
        )

    def get_show_matches(self, _, word_before_cursor):
        return self.find_matches(
            word_before_cursor,
            self.show_items,
            casing=self.keyword_casing
        )

    def get_user_matches(self, _, word_before_cursor):
        return self.find_matches(
            word_before_cursor,
            self.users
        )

    def get_special_matches(self, _, word_before_cursor):
        return self.find_matches(
            word_before_cursor,
            self.special_commands,
            start_only=True,
            fuzzy=True
        )

    def get_table_format_matches(self, _, word_before_cursor):
        return self.find_matches(
            word_before_cursor,
            self.table_formats,
            start_only=True,
            fuzzy=False
        )

    def get_file_name_matches(self, _, word_before_cursor):
        return self.find_files(word_before_cursor)

    suggestion_matchers = {
       'column': get_column_matches,
       'function': get_function_matches,
       'table': get_table_matches,
       'view': get_view_matches,
       'alias': get_alias_matches,
       'database': get_database_matches,
       'schema': get_schema_matches,
       'keyword': get_keyword_matches,
       'show': get_show_matches,
       'user': get_user_matches,
       'special': get_special_matches,
       'table_format': get_table_format_matches,
       'file_name': get_file_name_matches,
    }

    def find_files(self, word):
        """Yield matching directory or file names.
        :param word:
        :return: iterable
        """
        base_path, last_path, position = parse_path(word)
        paths = suggest_path(word)
        for name in sorted(paths):
            suggestion = complete_path(name, last_path)
            if suggestion:
                yield Completion(suggestion, position)

    def populate_scoped_cols(self, scoped_tbls):
        """Find all columns in a set of scoped_tables
        :param scoped_tbls: list of (schema, table, alias) tuples
        :return: list of column names
        """
        columns = []
        meta = self.dbmetadata

        for tbl in scoped_tbls:
            # A fully qualified schema.relname reference or default_schema
            # DO NOT escape schema names.
            schema = tbl[0] or self.dbname
            relname = tbl[1]
            escaped_relname = self.escape_name(tbl[1])

            # We don't know if schema.relname is a table or view. Since
            # tables and views cannot share the same name, we can check one
            # at a time
            try:
                columns.extend(meta['tables'][schema][relname])

                # Table exists, so don't bother checking for a view
                continue
            except KeyError:
                try:
                    columns.extend(meta['tables'][schema][escaped_relname])
                    # Table exists, so don't bother checking for a view
                    continue
                except KeyError:
                    pass

            try:
                columns.extend(meta['views'][schema][relname])
            except KeyError:
                pass

        return columns

    def populate_schema_objects(self, schema, obj_type):
        """Returns list of tables or functions for a (optional) schema"""
        metadata = self.dbmetadata[obj_type]
        schema = schema or self.dbname

        try:
            objects = metadata[schema].keys()
        except KeyError:
            # schema doesn't exist
            objects = []

        return objects