#!/usr/bin/env python3
#
# Copyright (C) 2018 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#

import sys
import os
import stat
import pwd
import copy
import glob

import jinja2
import vyos.validate

from vyos.config import Config
from vyos import ConfigError

config_file = r'/etc/default/tftpd'

# Please be careful if you edit the template.
config_tmpl = """
### Autogenerated by tftp_server.py ###
DAEMON_ARGS="--listen --user tftp --address {% for a in listen-%}{{ a }}{% endfor %}{% if allow_upload %} --create --umask 000{% endif %} --secure {{ directory }}"


"""

default_config_data = {
    'directory': '',
    'allow_upload': False,
    'port': '69',
    'listen': []
}

def get_config():
    tftpd = copy.deepcopy(default_config_data)
    conf = Config()
    if not conf.exists('service tftp-server'):
        return None
    else:
        conf.set_level('service tftp-server')

    if conf.exists('directory'):
        tftpd['directory'] = conf.return_value('directory')

    if conf.exists('allow-upload'):
        tftpd['allow_upload'] = True

    if conf.exists('port'):
        tftpd['port'] = conf.return_value('port')

    tftpd['listen'] = conf.return_values('listen-address')

    return tftpd

def verify(tftpd):
    # bail out early - looks like removal from running config
    if tftpd is None:
        return None

    # Configuring allowed clients without a server makes no sense
    if not tftpd['directory']:
        raise ConfigError('TFTP root directory must be configured!')

    if not tftpd['listen']:
        raise ConfigError('TFTP server listen address must be configured!')

    for addr in tftpd['listen']:
        if not vyos.validate.is_addr_assigned(addr):
            print('WARNING: TFTP server listen address {0} not assigned to any interface!'.format(addr))

    return None

def generate(tftpd):
    # cleanup any available configuration file
    # files will be recreated on demand
    for i in glob.glob(config_file + '*'):
        os.unlink(i)

    # bail out early - looks like removal from running config
    if tftpd is None:
        return None

    idx = 0
    for listen in tftpd['listen']:
        config = copy.deepcopy(tftpd)
        if vyos.validate.is_ipv4(listen):
            config['listen'] = [listen + ":" + tftpd['port'] + " -4"]
        else:
            config['listen'] = ["[" + listen + "]" + tftpd['port'] + " -6"]

        tmpl = jinja2.Template(config_tmpl)
        config_text = tmpl.render(config)
        file = config_file + str(idx)
        with open(file, 'w') as f:
            f.write(config_text)

        idx = idx + 1

    return None

def apply(tftpd):
    # stop all services first - then we will decide
    os.system('sudo systemctl stop tftpd@{0..20}')

    # bail out early - e.g. service deletion
    if tftpd is None:
        return None

    tftp_root = tftpd['directory']
    if not os.path.exists(tftp_root):
        os.makedirs(tftp_root)
        os.chmod(tftp_root, stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR|stat.S_IRGRP|stat.S_IXGRP|stat.S_IROTH|stat.S_IXOTH)

    # get UNIX uid for user 'tftp'
    tftp_uid = pwd.getpwnam('tftp').pw_uid
    tftp_gid = pwd.getpwnam('tftp').pw_gid

    # get UNIX uid for tftproot directory
    dir_uid = os.stat(tftp_root).st_uid
    dir_gid = os.stat(tftp_root).st_gid

    # adjust uid/gid of tftproot directory if files don't belong to user tftp
    if (tftp_uid != dir_uid) or (tftp_gid != dir_gid):
        os.chown(tftp_root, tftp_uid, tftp_gid)

    idx = 0
    for listen in tftpd['listen']:
        os.system('sudo systemctl restart tftpd@{0}.service'.format(idx))
        idx = idx + 1

    return None

if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        sys.exit(1)
