# -*- coding: utf-8 -*-

"""
A C compiler for construction.
"""

from django.conf import settings
from checker.compiler.Builder import Compiler 
from django.utils.translation import ugettext_lazy as _

class CBuilder(Compiler):
	""" A C compiler for construction. """

	# Initialization sets attributes to default values.
	_compiler		= settings.C_BINARY
	_language		= "C"
	#_rx_warnings		= r"^([^ :]*:[^:].*)$"

		
		
	def pre_run(self,env):
		return self.compiler()



	def post_run(self,env):
		passed = True
		log = ""
		return [passed,log]


	def connected_flags(self, env):     		
		return self.flags(env) + self.search_path()


from checker.admin import CheckerInline, AlwaysChangedModelForm

class CheckerForm(AlwaysChangedModelForm):
	""" override default values for the model fields """
	def __init__(self, **args):
		super(CheckerForm, self).__init__(**args)
		self.fields["_flags"].initial = "-Wall -Wextra"
		#self.fields["_output_flags"].initial = "-o %s"
		self.fields["_output_flags"].initial = "-c"
		#self.fields["_libs"].initial = ""
		self.fields["_file_pattern"].initial = r"^[a-zA-Z0-9_]*\.[cC]$"
#		self.fields["_main_required"].label = _("link as executable program")
#		self.fields["_main_required"].help_text = _("if not activated, code will be compiled to object file *.o! Compiler uses -c option")
	

class CBuilderInline(CheckerInline):
	model = CBuilder
	form = CheckerForm
	verbose_name = "C Compiler"

