# -*- coding: utf-8 -*-
# Copyright (c) 2016 Marko Dimjašević <marko@dimjasevic.net>
# Copyright (c) 2012-2013 Paul Tagliamonte <paultag@debian.org>
# Copyright (c) 2013 Leo Cavaille <leo@cavaille.net>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from debile.slave.wrappers.klee import parse_klee
from debile.utils.commands import run_command

import os
from schroot import schroot


def chroot_cmd_sequence(chroot, cmds):
    out_ = ""
    err_ = ""
    for cmd in cmds:
        if cmd[0] == 'root':
            out, err, ret = chroot.run(cmd[1], user='root')
        else:
            out, err, ret = chroot.run(cmd[1])
        out_ += out
        err_ += err
        if ret:
            return out_, err_, ret

    return out_, err_, 0

def install_llvm(chroot, llvm_ver):

    return chroot_cmd_sequence(chroot,
            [['root', ['apt-get', 'install', '--yes',
                       'clang-%s' % llvm_ver,
                       'llvm-%s' % llvm_ver,
                       'llvm-%s-dev' % llvm_ver,
                       'llvm-%s-tools' % llvm_ver,
                       'libllvm%s' % llvm_ver]]])

def install_wllvm(chroot, directory):
    out_ = ""
    tmp_dir, err_, ret = chroot.run([
        'mktemp', '--directory'
    ])
    if ret:
        return out_, err_, ret

    tmp_dir = tmp_dir.strip()
    archive = tmp_dir + "/wllvm.zip"
    gcc_ver_list = ['6', '5']
    compiler_map = {"g++" : "wllvm++", "gcc" : "wllvm", "cpp" : "wllvm"}

    wllvm_cmds_1 = [
        ['root', ['apt-get', 'install', '--yes',
                  'wget', 'unzip', 'ca-certificates', 'rsync']],
        ['', ['wget',
              'https://github.com/travitch/whole-program-llvm/archive/master.zip',
              '-O', archive]],
        ['', ['unzip', archive, '-d', tmp_dir]]
    ]
    wllvm_cmds_2 = [
        ['root', ['rsync', '-a', tmp_dir + '/whole-program-llvm-master/' + wllvm_file,
                  directory + "/"]]
        for wllvm_file in ['driver',
                                    'sanity', 'extract-bc', 'wllvm',
                                    'wllvm++', 'wllvm-sanity-checker']
    ]
    wllvm_cmds_3 = [
        ['root', ['chmod', '+x',
                  directory + '/wllvm',
                  directory + '/wllvm++',
                  directory + '/extract-bc']],
    ]
    wllvm_cmds = wllvm_cmds_1 + wllvm_cmds_2 + wllvm_cmds_3

    gcc_cmds = []
    for gcc_ver in gcc_ver_list:
        for tool in compiler_map.keys():
            gcc_cmds += [['root', ['apt-get', 'install', '--yes',
                          '%s-%s' % (tool, gcc_ver)]]]

    rm_cmds = [['root', ['rm', '-f',
                         directory + '/%s-%s' % (tool, gcc_ver)]]
               for gcc_ver in gcc_ver_list for tool in compiler_map.keys()]
    ln_cmds = [['root', ['ln', '-s',
                         directory + '/' + v,
                         directory + '/%s-%s' % (k, gcc_ver)]]
               for k, v in compiler_map.iteritems()
               for gcc_ver in gcc_ver_list]

    dpkg_hold_cmds = []
    for tool in compiler_map.keys():
        for gcc_ver in gcc_ver_list:
            dpkg_hold_cmds += [['root', ['sh', '-c',
                                         ('echo {0}-{1} hold | dpkg ' +
                                          '--set-selections').format(
                                              tool, gcc_ver)]]]
        dpkg_hold_cmds += [['root', ['sh', '-c',
                                     ('echo {0} hold | dpkg ' +
                                      '--set-selections').format(tool)]]]

    return chroot_cmd_sequence(chroot,
            wllvm_cmds + gcc_cmds + rm_cmds + ln_cmds + dpkg_hold_cmds)

def install_klee(chroot):

    stp_pkg  = "stp_2.1.1+dfsg-1_amd64.deb"
    stp_pkg_path = "/tmp/" + stp_pkg
    klee_pkg = "klee_1.2.0-1_amd64.deb"
    klee_pkg_path = "/tmp/" + klee_pkg
    url_dir  = "https://dimjasevic.net/marko/klee"
    cmds = [
        ['root', ['apt-get', 'install', '--yes',
                  'libboost-program-options1.55.0', 'libgcc1', 'libstdc++6',
                  'minisat', 'libcap2', 'libffi6', 'libtinfo5', 'python',
                  'python-tabulate']],
        ['', ['wget', '%s/%s' % (url_dir, stp_pkg), '-O', stp_pkg_path]],
        ['', ['wget', '%s/%s' % (url_dir, klee_pkg), '-O', klee_pkg_path]],
        ['root', ['dpkg', '--install', stp_pkg_path]],
        ['root', ['dpkg', '--install', klee_pkg_path]],
        ['', ['rm', stp_pkg_path, klee_pkg_path]]
    ]

    return chroot_cmd_sequence(chroot, cmds)

def klee(package, suite, arch, analysis):
    chroot_name = "%s-%s" % (suite, arch)

    # At the moment KLEE can be run on amd64 only
    if arch != 'amd64':
        raise ValueError("KLEE is supported on amd64 only")

    with schroot(chroot_name) as chroot:
        dsc = os.path.basename(package)
        if not dsc.endswith('.dsc'):
            raise ValueError("KLEE runner must receive a .dsc file")

        bin_dir = '/usr/bin'
        out_ = ""
        err_ = ""

        # Because LLVM 3.4 is not available as of Debian Stretch, but
        # only versions 3.6 and higher, we use snapshot.debian.org to
        # install LLVM
        sources_list_path = '/etc/apt/sources.list'
        out, err, ret = chroot.run(['sh', '-c',
                                    'echo deb http://snapshot.debian.org/' +
                                    'archive/debian/20160707T223519Z/ ' +
                                    'jessie main >> ' + sources_list_path],
                                   user='root')
        if ret:
            raise Exception(err)
        out_ += out
        err_ += err

        out, err, ret = chroot.run(['apt-get', 'update'], user='root')
        if ret:
            raise Exception(err)
        out_ += out
        err_ += err
        
        # Install Clang and LLVM packages needed for KLEE
        llvm_ver = '3.4'
        out, err, ret = install_llvm(chroot, llvm_ver)
        if ret:
            raise Exception(err)
        out_ += out
        err_ += err

        # Install WLLVM
        out, err, ret = install_wllvm(chroot, bin_dir)
        if ret:
            raise Exception(err)
        out_ += out
        err_ += err

        # Install KLEE and its dependencies
        out, err, ret = install_klee(chroot)
        if ret:
            raise Exception(err)
        out_ += out
        err_ += err

    # Run the build process for the package given by the dsc
    # parameter. That will use WLLVM (with Clang) instead of the usual
    # GCC.
    #
    # I cannot run dpkg-buildpackage directly. I need to do something
    # on the .dsc file. Probably I need to run dpkg -b dsc. See
    # runners/clanganalyzer.py for an example of building a package
    # in an schroot.
    #
    # _, err, ret = run_command(["dpkg-buildpackage", "-us", "-uc"])
    # if ret != 0:
    #     raise Exception("Package building failed: " + err)

    # See how to set up an sbuild environment for KLEE

def version():
    out, _, ret = run_command(['klee', '-version'])
    if ret != 1:
        # Yes, KLEE returns 1 when executed with the '-version'
        # parameter
        raise Exception("KLEE is not installed")

    line_list = out.split('\n')[0].split(' ')
    tool_name = line_list[0]
    tool_version = line_list[1]
    return (tool_name, tool_version)
