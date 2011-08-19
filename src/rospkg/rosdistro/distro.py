# Software License Agreement (BSD License)
#
# Copyright (c) 2010, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Representation/model of rosdistro format.
"""

import os
import sys
import urllib2
import yaml

class DistroException(Exception): pass

class InvalidDistro(DistroException): pass

def expand_rule(rule, stack_name, stack_ver, release_name, revision=None):
    s = rule.replace('$STACK_NAME', stack_name)
    if stack_ver:
        s = s.replace('$STACK_VERSION', stack_ver)
    s =    s.replace('$RELEASE_NAME', release_name)
    if s.find('$REVISION') > 0 and not revision:
        raise DistroException("revision specified but not supplied by build_release")
    elif revision:
        s = s.replace('$REVISION', revision)
    return s

class DistroStack(object):
    """Stores information about a stack release"""

    def __init__(self, stack_name, rules, stack_version):
        self.name = stack_name
        self._rules = rules
        self._update_version(stack_version)
        self.repo = rules.get('repo', None)

    def _update_version(self, stack_version):
        rules = self._rules
        self.version = stack_version
        self.vcs_config = load_vcs_config(rules, self._expand_rule)

    def _expand_rule(self, rule):
        """
        Perform variable substitution on stack rule.
        """
        return expand_rule(rule, self.name, self.version, self.release_name)
        
    def __eq__(self, other):
        if not isinstance(other, DistroStack):
            return False
        return self.name == other.name and \
            self.version == other.version and \
            self.vcs_config == other.vcs_config

class Variant(object):
    """
    A variant defines a specific set of stacks ("metapackage", in Debian
    parlance). For example, "base", "pr2". These variants can extend
    another variant.
    """

    def __init__(self, variant_name, variants_props):
        """
        @param variant_name: name of variant to load from distro file
        @type  variant_name: str
        @param variants_props: dictionary mapping variant names to the rosdistro map for that variant

        @raise InvalidDistro
        """
        self.name = variant_name
        self.parents = []
        
        # save the properties for our particular variant
        props = variants_props[variant_name]

        # load in variant properties from distro spec
        if not 'stacks' in props and not 'extends' in props:
            raise InvalidDistro("variant properties must define 'stacks' or 'extends':\n%s"%(props))

        # stack_names accumulates the full expanded list
        self.stack_names = list(props.get('stacks', []))
        # stack_names_explicit is only the stack names directly specified
        self.stack_names_explicit = self.stack_names[:]
        
        # check to see if we extend another distro, in which case we prepend their props
        if 'extends' in props:
            extends = props['extends']
            if type(extends) == type('str'):
                extends = [extends]
            # store parents property for debian metapackages
            self.parents = extends

            for e in extends:
                parent_variant = Variant(e, variants_props)
                self.stack_names = parent_variant.stack_names + self.stack_names
        self._props = props
      
class Distro(object):
    """
    Store information in a rosdistro file.
    """
    
    def __init__(self, stacks, variants, release_name, version, raw_data):
        """
        @param source_uri: source URI of distro file, or path to distro file
        """
        self.stacks = stacks
        self.variants = variants
        self.release_name = release_name
        self.version = version
        self.raw_data = raw_data

    def get_stack_names(self, released=False):
        if released:
            return get_released_stacks().keys()
        else:
            return self.stacks.keys()

    def get_released_stacks(self):
        retval = {}
        for s, obj in self.stacks.items(): #py3k
            if obj.version:
                retval[s] = obj
        return retval

    released_stacks = property(get_released_stacks)
    stack_names = property(get_stack_names)

def load_distro(source_uri):
    """
    @param source_uri: source URI of distro file, or path to distro file
    """
    try:
        # parse rosdistro yaml
        if os.path.isfile(source_uri):
            # load rosdistro file
            with open(source_uri) as f:
                raw_data = yaml.load(f.read())
        else:
            raw_data = yaml.load(urllib2.urlopen(source_uri))
    except yaml.YAMLError as e:
        raise InvalidDistro(str(e))

    try:
        stack_props = y['stacks']
        stack_names = [x for x in stack_props.keys() if not x[0] == '_']
        version = _distro_version(raw_data.get('version', '0'))
        release_name = raw_data['release']

        variants = {}
        variant_props = {}
        for props in y['variants']:
            if len(props.keys()) != 1:
                raise InvalidDistro("invalid variant spec: %s"%props)
            n = props.keys()[0]
            variant_props[n] = props[n]
            #TODO: process variant props here, instead of in constructor

    except KeyError as e:
        raise InvalidDistro("distro is missing required '%s' key"%(str(e)))

    stacks = _load_distro_stacks(raw_data, stack_names, release_name=release_name, version=version)
    for v, variant_props in variant_props.keys():
        variants[v] = Variant(v, variants)

    return Distro(stacks, variants, release_name, version, raw_data)

def _load_distro_stacks(distro_doc, stack_names):
    """
    @param distro_doc: dictionary form of rosdistro file
    @type distro_doc: dict
    @param stack_names: names of stacks to load
    @type  stack_names: [str]
    @return: dictionary of stack names to DistroStack instances
    @rtype: {str : DistroStack}
    @raise DistroException: if distro_doc format is invalid
    """

    # load stacks and expand out uri rules
    stacks = {}
    try:
        stack_props = distro_doc['stacks']
    except KeyError:
        raise DistroException("distro is missing required 'stacks' key")
    for stack_name in stack_names:
        # ignore private keys like _rules
        if stack_name[0] == '_':
            continue

        stack_version = stack_props[stack_name].get('version', None)
        rules = get_rules(distro_doc, stack_name)
        stacks[stack_name] = DistroStack(stack_name, rules, stack_version)
    return stacks

def _distro_version(version_val):
    """
    Parse distro version value, converting SVN revision to version value if necessary
    """
    version_val = str(version_val)
    m = re.search('\$Revision:\s*([0-9]*)\s*\$', version_val)
    if m is not None:
        version_val = 'r'+m.group(1)

    # Check that is a valid version string
    valid = string.ascii_letters + string.digits + '.+~'
    if False in (c in valid for c in version_val):
        raise InvalidDistro("Version string %s not valid"%version_val)
    return version_val
