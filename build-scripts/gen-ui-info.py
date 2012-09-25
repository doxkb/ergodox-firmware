#! /usr/bin/env python3
# -----------------------------------------------------------------------------

"""
Generate UI info file (in JSON) (format version: 0)

The file will contain:
{
  ".meta-data": {
      "version": <number>,
      "date-generated": <string>,
  },
  "keyboard-functions": {
      <(function name)>: {
          "position": <number>,
          "length": <number>,
          "comments": {
              "name": <string>,
              "description": <string>,
              "notes": [
                  <string>,
                  ...
              ],
              ...
          }
      },
      ...
  },
  "layout-matrices": {
      <(matrix name)>: {
          "position": <number>,
          "length": <number>
      },
      ...
  },
  "miscellaneous": {
      "git-commit-date": <string>,
      "git-commit-id": <string>,
      "number-of-layers": <number>
  }
}

Depends on:
- the project source code
- the project '.map' file (generated by the compiler)
-----------------------------------------------------------------------------
Copyright (c) 2012 Ben Blazak <benblazak.dev@gmail.com>
Released under The MIT License (MIT) (see "license.md")
Project located at <https://github.com/benblazak/ergodox-firmware>
-----------------------------------------------------------------------------
"""

# -----------------------------------------------------------------------------

import argparse
import json
import os
import re
import subprocess
import sys

# -----------------------------------------------------------------------------

def gen_static(git_commit_date=None, git_commit_id=None):
	"""Generate static information"""

	date = None
	if os.name == 'posix':
		date = subprocess.getoutput('date --rfc-3339 s')

	return {
		'.meta-data': {
			'version': 0,  # the format version number
			'date-generated': date,
		},
		'miscellaneous': {
			'git-commit-date': git_commit_date, # should be passed by makefile
			'git-commit-id': git_commit_id, # should be passed by makefile
		},
	}

def gen_derived(data):
	"""
	Generate derived information
	Should be called last
	"""
	return {
		'miscellaneous': {
			'number-of-layers':
				int( data['layout-matrices']['_kb_layout']['length']/(6*14) ),
				# because 6*14 is the number of bytes/layer for '_kb_layout'
				# (which is a uint8_t matrix)
		},
	}

# -----------------------------------------------------------------------------

def parse_mapfile(map_file_path):
	"""Parse the '.map' file"""

	def parse_keyboard_function(f, line):
		"""Parse keyboard-functions in the '.map' file"""

		search = re.search(r'(0x\S+)\s+(0x\S+)', next(f))
		position = int( search.group(1), 16 )
		length = int( search.group(2), 16 )

		search = re.search(r'0x\S+\s+(\S+)', next(f))
		name = search.group(1)

		return {
			'keyboard-functions': {
				name: {
					'position': position,
					'length': length,
				},
			},
		}

	def parse_layout_matrices(f, line):
		"""Parse (all 3) layout matrices"""

		search = re.search(r'0x\S+\s+(0x\S+)', line)
		# (length for (size of, in bytes) a layer of 1 byte objects)
		base_length = int( int( search.group(1), 16 ) / 5 )

		next_lines = ''.join([next(f), next(f), next(f)])
		layout_position = re.search(
				r'(0x\S+)\s+_kb_layout'+'\n', next_lines ) . group(1)
		layout_press_position = re.search(
				r'(0x\S+)\s+_kb_layout_press'+'\n', next_lines ) . group(1)
		layout_release_position = re.search(
				r'(0x\S+)\s+_kb_layout_release'+'\n', next_lines ) . group(1)
		layout_position = int(layout_position, 16)
		layout_press_position = int(layout_press_position, 16)
		layout_release_position = int(layout_release_position, 16)

		if not ( layout_position
		         and layout_press_position
		         and layout_release_position ):
			   raise Exception(
					   "parse_mapfile: not all layout matrices were found" )

		return {
			'layout-matrices': {
				'_kb_layout': {
					'position': layout_position,
					'length': base_length,
				},
				'_kb_layout_press': {
					'position': layout_press_position,
					'length': base_length * 2,
				},
				'_kb_layout_release': {
					'position': layout_release_position,
					'length': base_length * 2,
				},
			},
		}

	# --- parse_mapfile() ---

	# normalize paths
	map_file_path = os.path.abspath(map_file_path)
	# check paths
	if not os.path.exists(map_file_path):
		raise ValueError("invalid 'map_file_path' given")

	output = {}

	f = open(map_file_path)

	for line in f:
		if re.search(r'^\s*\.text\.kbfun_', line):
			dict_merge(output, parse_keyboard_function(f, line))
		elif re.search(r'^\s*\.progmem\.data.*layout', line):
			dict_merge(output, parse_layout_matrices(f, line))

	return output


def parse_source_code(source_code_path):
	"""Parse all files in the source directory"""

	def read_comments(f, line):
		"""
		Read in properly formatted multi-line comments
		- Comments must start with '/*' and end with '*/', each on their own
		  line
		"""
		comments = ''
		while(line.strip() != r'*/'):
			comments += line[2:].strip()+'\n'
			line = next(f)
		return comments

	def parse_comments(comments):
		"""
		Parse an INI style comment string
		- Fields begin with '[field-name]', and continue until the next field,
		  or the end of the comment
		- Fields '[name]', '[description]', and '[note]' are treated specially
		"""

		def add_field(output, field, value):
			"""Put a field+value pair in 'output', the way we want it, if the
			pair is valid"""

			value = value.strip()

			if field is not None:
				if field in ('name', 'description'):
					if field not in output:
						output[field] = value
				else:
					if field == 'note':
						field = 'notes'

					if field not in output:
						output[field] = []

					output[field] += [value]

		# --- parse_comments() ---

		output = {}

		field = None
		value = None
		for line in comments.split('\n'):
			line = line.strip()

			if re.search(r'^\[.*\]$', line):
				add_field(output, field, value)
				field = line[1:-1]
				value = None

			else:
				if value is None:
					value = ''
				if len(value) > 0 and value[-1] == '.':
					line = ' '+line
				value += ' '+line

		add_field(output, field, value)

		return output

	def parse_keyboard_function(f, line, comments):
		"""Parse keyboard-functions in the source code"""

		search = re.search(r'void\s+(kbfun_\S+)\s*\(void\)', line)
		name = search.group(1)

		return {
			'keyboard-functions': {
				name: {
					'comments': parse_comments(comments),
				},
			},
		}

	# --- parse_source_code() ---

	# normalize paths
	source_dir_path = os.path.abspath(source_code_path)
	# check paths
	if not os.path.exists(source_code_path):
		raise ValueError("invalid 'source_dir_path' given")

	output = {}

	for tup in os.walk(source_code_path):
		for file_name in tup[2]:
			# normalize paths
			file_name = os.path.abspath( os.path.join( tup[0], file_name ) )

			# ignore non '.c' files
			if file_name[-2:] != '.c':
				continue

			f = open(file_name)

			comments = ''
			for line in f:
				if line.strip() == r'/*':
					comments = read_comments(f, line)
				elif re.search(r'void\s+kbfun_\S+\s*\(void\)', line):
					dict_merge(
							output,
							parse_keyboard_function(f, line, comments) )

	return output

# -----------------------------------------------------------------------------

def dict_merge(a, b):
	"""
	Recursively merge two dictionaries
	- I was looking around for an easy way to do this, and found something
	  [here]
	  (http://www.xormedia.com/recursively-merge-dictionaries-in-python.html).
	  This is pretty close, but i didn't copy it exactly.
	"""

	if not isinstance(a, dict) or not isinstance(b, dict):
		return b

	for (key, value) in b.items():
		if key in a:
			a[key] = dict_merge(a[key], value)
		else:
			a[key] = value

	return a

# -----------------------------------------------------------------------------

def main():
	arg_parser = argparse.ArgumentParser(
			description = 'Generate project data for use with the UI' )

	arg_parser.add_argument(
			'--git-commit-date',
			help = ( "should be in the format rfc-3339 "
				   + "(e.g. 2006-08-07 12:34:56-06:00)" ),
			required = True )
	arg_parser.add_argument(
			'--git-commit-id',
			help = "the git commit ID",
			required = True )
	arg_parser.add_argument(
			'--map-file-path',
			help = "the path to the '.map' file",
			required = True )
	arg_parser.add_argument(
			'--source-code-path',
			help = "the path to the source code directory",
			required = True )

	args = arg_parser.parse_args(sys.argv[1:])

	output = {}
	dict_merge(output, gen_static(args.git_commit_date, args.git_commit_id))
	dict_merge(output, parse_mapfile(args.map_file_path))
	dict_merge(output, parse_source_code(args.source_code_path))
	dict_merge(output, gen_derived(output))

	print(json.dumps(output, sort_keys=True, indent=4))

# -----------------------------------------------------------------------------

if __name__ == '__main__':
	main()

