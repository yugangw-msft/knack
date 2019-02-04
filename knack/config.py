# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import os
import sys
import stat
from six.moves import configparser

from .util import ensure_dir

_UNSET = object()


def get_config_parser():
    return configparser.ConfigParser() if sys.version_info.major == 3 else configparser.SafeConfigParser()


class CLIConfig(object):
    _BOOLEAN_STATES = {'1': True, 'yes': True, 'true': True, 'on': True,
                       '0': False, 'no': False, 'false': False, 'off': False}

    _DEFAULT_CONFIG_ENV_VAR_PREFIX = 'CLI'
    _DEFAULT_CONFIG_DIR = os.path.join('~', '.{}'.format('cli'))
    _DEFAULT_CONFIG_FILE_NAME = 'config'

    def __init__(self, config_dir=None, config_env_var_prefix=None, config_file_name=None,
                 use_local_config=False):
        """ Manages configuration options available in the CLI

        :param config_dir: The directory to store config files
        :type config_dir: str
        :param config_env_var_prefix: The prefix for config environment variables
        :type config_env_var_prefix: str
        :param config_file_name: The name given to the config file to be created
        :type config_file_name: str
        """
        config_dir = config_dir or CLIConfig._DEFAULT_CONFIG_DIR
        self.config_parser = get_config_parser()
        config_env_var_prefix = config_env_var_prefix or CLIConfig._DEFAULT_CONFIG_ENV_VAR_PREFIX
        env_var_prefix = '{}_'.format(config_env_var_prefix.upper())

        self._env_var_format = '{}{}'.format(env_var_prefix, '{section}_{option}')

        config_file_name = config_file_name or CLIConfig._DEFAULT_CONFIG_FILE_NAME
        self.config_dir = config_dir = os.path.expanduser(config_dir)
        self.config_file_chain = []
        if use_local_config:  # TODO handle edge case that the current folder is the ~/.azure
            current_dir = os.getcwd()
            config_dir_name = os.path.basename(config_dir)
            while current_dir:  # TODO handle when .azure doesn't exist or accessing it might throw
                current_config_dir = os.path.join(current_dir, config_dir_name)
                self.config_file_chain.append(_ConfigFile(current_config_dir,
                                                          os.path.join(current_config_dir, config_file_name)))
                if current_dir == os.path.dirname(current_dir):
                    break
                current_dir = os.path.dirname(current_dir)
        self.config_file_chain.append(_ConfigFile(config_dir, os.path.join(config_dir, config_file_name)))

    def env_var_name(self, section, option):
        return self._env_var_format.format(section=section.upper(),
                                           option=option.upper())

    def has_option(self, section, option):
        if self.env_var_name(section, option) in os.environ:
            return True
        return bool(next((f for f in self.config_file_chain if f.has_option(section, option)), False))

    def get(self, section, option, fallback=_UNSET):
        env = self.env_var_name(section, option)
        if env in os.environ:
            return os.environ[env]
        last_ex = None
        for config in self.config_file_chain:
            try:
                return config.get(section, option)
            except (configparser.NoSectionError, configparser.NoOptionError) as ex:
                last_ex = ex

        if fallback is _UNSET:
            raise last_ex
        else:
            return fallback

    def items(self, section):
        import re
        pattern = self._env_var_format.split('_')[0] + '_' + section + '_.+' 
        candidates = [(k.split('_')[-1], os.environ[k], k) for k in os.environ.keys() if re.match(pattern, k)]
        result = {c[0]:c for c in candidates}
        for config in self.config_file_chain:
            try:
                entries = config.items(section)
                for name, value in entries:
                    if name not in result:
                        result[name] = (name, value, config.config_path)
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass
        # return list(result.values())  
        return  [{'name': name, 'value': value, 'source': source} for name, value, source in  result.values()]

    def getint(self, section, option, fallback=_UNSET):
        return int(self.get(section, option, fallback))

    def getfloat(self, section, option, fallback=_UNSET):
        return float(self.get(section, option, fallback))

    def getboolean(self, section, option, fallback=_UNSET):
        val = str(self.get(section, option, fallback))
        if val.lower() not in CLIConfig._BOOLEAN_STATES:
            raise ValueError('Not a boolean: {}'.format(val))
        return CLIConfig._BOOLEAN_STATES[val.lower()]

    def set(self, config):
        self.config_file_chain[0].set(config)

    def set_value(self, section, option, value):
        self.config_file_chain[0].set_value(section, option, value)


class _ConfigFile(object):

    def __init__(self, config_dir, config_path):
        self.config_dir = config_dir
        self.config_path = config_path
        self.config_parser = None
        if os.path.exists(config_path):
            self.config_parser = get_config_parser()
            self.config_parser.read(config_path)

    def items(self, section):
        return self.config_parser.items(section) if self.config_parser else []

    def has_option(self, section, option):
        return self.config_parser.has_option(section, option) if self.config_parser else False

    def get(self, section, option):
        if self.config_parser:
            return self.config_parser.get(section, option)
        else:
            raise configparser.NoOptionError(section, option)

    def getint(self, section, option):
        return int(self.get(section, option))

    def getfloat(self, section, option):
        return float(self.get(section, option))

    def getboolean(self, section, option):
        val = str(self.get(section, option))
        if val.lower() not in CLIConfig._BOOLEAN_STATES:
            raise ValueError('Not a boolean: {}'.format(val))
        return CLIConfig._BOOLEAN_STATES[val.lower()]

    def set(self, config):
        ensure_dir(self.config_dir)
        with open(self.config_path, 'w') as configfile:
            config.write(configfile)
        os.chmod(self.config_path, stat.S_IRUSR | stat.S_IWUSR)
        config.read(self.config_path)

    def set_value(self, section, option, value):
        config = get_config_parser()
        config.read(self.config_path)
        try:
            config.add_section(section)
        except configparser.DuplicateSectionError:
            pass
        config.set(section, option, value)
        self.set(config)
