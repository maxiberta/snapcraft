# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2015-2016 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

from unittest import mock

import snapcraft
from snapcraft import tests
from snapcraft.plugins import python


def setup_directories(plugin, python_version):
    version = '2.7' if python_version == 'python2' else '3.5'
    os.makedirs(plugin.sourcedir)
    os.makedirs(os.path.join(
        plugin.installdir, 'usr', 'lib', 'python' + version, 'dist-packages'))
    os.makedirs(os.path.join(
        plugin.installdir, 'usr', 'include', 'python' + version))
    open('setup.py', 'w').close()


class PythonPluginTestCase(tests.TestCase):

    def setUp(self):
        super().setUp()

        class Options:
            source = '.'
            requirements = ''
            constraints = ''
            python_version = 'python3'
            python_packages = []
            process_dependency_links = False

        self.options = Options()
        self.project_options = snapcraft.ProjectOptions()

        patcher = mock.patch('subprocess.check_call')
        self.mock_call = patcher.start()
        self.addCleanup(patcher.stop)

    def test_schema(self):
        schema = python.PythonPlugin.schema()
        expected_requirements = {'type': 'string'}
        expected_constraints = {'type': 'string'}
        expected_python_packages = {
            'type': 'array',
            'minitems': 1,
            'uniqueItems': True,
            'items': {'type': 'string'},
            'default': [],
        }
        extend_pull = ['requirements', 'constraints', 'python-packages']

        self.assertDictEqual(expected_requirements,
                             schema['properties']['requirements'])
        self.assertDictEqual(expected_constraints,
                             schema['properties']['constraints'])
        self.assertDictEqual(expected_python_packages,
                             schema['properties']['python-packages'])
        self.assertTrue(
            set(extend_pull).issubset(set(schema['pull-properties']))
        )

    def test_env(self):
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        expected_env = [
            'PYTHONUSERBASE=/testpath',
            'PYTHONHOME=/testpath/usr',
        ]
        env = plugin.env('/testpath')
        self.assertListEqual(expected_env, env)

        env_missing_path = plugin.env('/testpath')
        self.assertTrue('PYTHONPATH=/testpath' not in env_missing_path)

    def test_system_pip_command(self):
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        pip_command = os.path.join(os.path.sep, 'usr', 'bin', 'pip3')
        self.assertEqual(plugin.system_pip_command, pip_command)

        # NOTE(SamYaple): python2 pip test
        self.options.python_version = 'python2'
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        pip_command = os.path.join(os.path.sep, 'usr', 'bin', 'pip')
        self.assertEqual(plugin.system_pip_command, pip_command)

    @mock.patch.object(python.PythonPlugin, '_run_pip')
    def test_pull(self, mock_pip):
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        plugin.pull()
        self.assertTrue(mock_pip.called)

    @mock.patch.object(python.PythonPlugin, 'run')
    @mock.patch.object(os.path, 'exists', return_value=False)
    def test_missing_setup_path(self, mock_path_exists, mock_run):
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        setup_directories(plugin, self.options.python_version)
        plugin.pull()
        self.assertFalse(mock_run.called)

    @mock.patch.object(python.PythonPlugin, 'run')
    def test_pip(self, mock_run):
        self.options.requirements = 'requirements.txt'
        self.options.constraints = 'constraints.txt'
        self.options.python_packages = ['test', 'packages']

        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        setup_directories(plugin, self.options.python_version)

        requirements_path = os.path.join(plugin.sourcedir, 'requirements.txt')
        constraints_path = os.path.join(plugin.sourcedir, 'constraints.txt')
        pip_install = ['pip', 'install', '--user', '--no-compile',
                       '--disable-pip-version-check',
                       '--constraint', constraints_path]

        calls = [
            mock.call(pip_install + ['--requirement', requirements_path],
                      env=mock.ANY),
            mock.call(pip_install + ['test', 'packages'],
                      env=mock.ANY),
            mock.call(pip_install + ['.'], cwd=plugin.sourcedir,
                      env=mock.ANY),
        ]
        plugin.pull()
        mock_run.assert_has_calls(calls)

    @mock.patch.object(python.PythonPlugin, 'run')
    def test_pip_with_url(self, mock_run):
        self.options.requirements = 'https://test.com/requirements.txt'
        self.options.constraints = 'http://test.com/constraints.txt'

        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        setup_directories(plugin, self.options.python_version)

        pip_install = ['pip', 'install', '--user', '--no-compile',
                       '--disable-pip-version-check',
                       '--constraint', 'http://test.com/constraints.txt']

        calls = [
            mock.call(pip_install + ['--requirement',
                                     'https://test.com/requirements.txt'],
                      env=mock.ANY),
            mock.call(pip_install + ['.'], cwd=plugin.sourcedir,
                      env=mock.ANY),
        ]
        plugin.pull()
        mock_run.assert_has_calls(calls)

    def test_fileset_ignores(self):
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        expected_fileset = [
            '-bin/pip*',
            '-bin/easy_install*',
            '-bin/wheel',
            '-**/__pycache__',
            '-**/*.pyc',
        ]
        fileset = plugin.snap_fileset()
        self.assertListEqual(expected_fileset, fileset)

    @mock.patch.object(python.PythonPlugin, 'run')
    def test_build_fixes_python_shebangs(self, run_mock):
        if self.options.python_version == 'python2':
            py_version_short = 'python2'
            py_version_long = 'python2'
        elif self.options.python_version == 'python3':
            py_version_short = 'python3'
            py_version_long = 'python3.5'

        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        os.makedirs(plugin.sourcedir)
        open(os.path.join(plugin.sourcedir, 'setup.py'), 'w').close()
        os.makedirs(os.path.join(plugin.installdir, 'bin'))
        os.makedirs(os.path.join(
            plugin.installdir, 'usr', 'lib', py_version_long, 'dist-packages'))
        os.makedirs(os.path.join(
            plugin.installdir, 'usr', 'include', py_version_long))

        # Place a few files with bad shebangs, and some files that shouldn't be
        # changed.
        files = [
            {
                'path': os.path.join(plugin.installdir, 'example.py'),
                'contents': '#!/foo/bar/baz/python',
                'expected': '#!/usr/bin/env python',
            },
            {
                'path': os.path.join(plugin.installdir, 'bin/another_example'),
                'contents': '#!/foo/baz/' + py_version_short,
                'expected': '#!/usr/bin/env ' + py_version_short,
            },
            {
                'path': os.path.join(plugin.installdir, 'foo'),
                'contents': 'foo',
                'expected': 'foo',
            },
            {
                'path': os.path.join(plugin.installdir, 'bar'),
                'contents': 'bar\n#!/usr/bin/python3',
                'expected': 'bar\n#!/usr/bin/python3',
            }
        ]

        for file_info in files:
            with open(file_info['path'], 'w') as f:
                f.write(file_info['contents'])

        plugin.build()

        for file_info in files:
            with open(os.path.join(plugin.installdir,
                                   file_info['path']), 'r') as f:
                self.assertEqual(f.read(), file_info['expected'])

    @mock.patch.object(python.PythonPlugin, 'run')
    def test_process_dependency_links(self, run_mock):
        self.options.process_dependency_links = True
        plugin = python.PythonPlugin('test-part', self.options,
                                     self.project_options)
        setup_directories(plugin, self.options.python_version)
        plugin.pull()
        self.assertIn('--process-dependency-links', run_mock.call_args[0][0])

    @mock.patch.object(os, 'stat')
    @mock.patch.object(os.path, 'exists', return_value=False)
    def test_replicate_owner_mode_missing_path(self, mock_path_exists,
                                               mock_os_stat):
        python._replicate_owner_mode('/nonexistant_path')
        self.assertFalse(mock_os_stat.called)
