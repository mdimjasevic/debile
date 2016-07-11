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
from debile.slave.utils import cd
from debile.utils.commands import run_command

import os


def klee(package, suite, arch, analysis):
    chroot_name = "%s-%s" % (suite, arch)

    # At the moment KLEE can be run on amd64 only
    if arch != 'amd64':
        raise ValueError("KLEE is supported on amd64 only")

    with schroot(chroot_name) as chroot:
        dsc = os.path.basename(package)
        if not dsc.endswith('.dsc'):
            raise ValueError("KLEE runner must receive a .dsc file")

        # Set up the chroot for KLEE. This includes:
        #   1. Installing Clang and LLVM 3.4
        #   2. Installing WLLVM
        #   3. Installing KLEE
        
        # Because LLVM 3.4 is not available as of Debian Stretch, but
        # only versions 3.6 and higher, we will use snapshot.debian.org to install LLVM

        out, err, ret = chroot.run([
            'echo',
            '"deb     http://snapshot.debian.org/archive/debian/20160707T223519Z/ jessie main"',
            '>>', '/etc/apt/sources.list'
        ], user='root')
        
        # out, err, ret = chroot.run([
        #     'echo',
        #     '"deb-src-http://snapshot.debian.org/archive/debian/20160707T223519Z/ jessie main"',
        #     '>>', '/etc/apt/sources.list'
        # ], user='root')

        out, err, ret = chroot.run([
            'apt-get', 'update'
        ], user='root')

        # Install Clang and LLVM needed for KLEE
        ver='3.4'
        out, err, ret = chroot.run([
            'apt-get', 'install', '--yes',
            'clang-%s llvm-%s llvm-%s-dev llvm-%s-tools' % (ver, ver, ver, ver)
        ], user='root')

        # Redirect all invocations of GCC compilers to WLLVM compiler
        # wrappers
        gcc_ver_list=['6', '5']
        bin_dir = '/usr/bin'
        for gcc_ver in gcc_ver_list:
            out, err, ret = chroot.run([
                'cd', bin_dir, '&&',
                'rm',
                'g++-%s' % gcc_ver,
                'gcc-%s' % gcc_ver,
                'cpp-%s' % gcc_ver
            ], user='root')

            out, err, ret = chroot.run([
                'cd', bin_dir, '&&',
                'ln', '-s', 'wllvm++', 'g++-%s' % gcc_ver
            ], user='root')
            out, err, ret = chroot.run([
                'cd', bin_dir, '&&',
                'ln', '-s', 'wllvm', 'gcc-%s' % gcc_ver
            ], user='root')
            out, err, ret = chroot.run([
                'cd', bin_dir, '&&',
                'ln', '-s', 'wllvm', 'cpp+-%s' % gcc_ver
            ], user='root')
    # Run the build process for the package given by the dsc
    # parameter. That will use WLLVM (with Clang) instead of the usual
    # GCC.
    #
    # I cannot run dpkg-buildpackage directly. I need to do something
    # on the .dsc file. Probably I need to run dpkg -b dsc. See
    # runners/clanganalyzer.py for an example of building a package
    # in an schroot.
    #
    _, err, ret = run_command(["dpkg-buildpackage", "-us", "-uc"])
    if ret != 0:
        raise Exception("Package building failed: " + err)

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
    
