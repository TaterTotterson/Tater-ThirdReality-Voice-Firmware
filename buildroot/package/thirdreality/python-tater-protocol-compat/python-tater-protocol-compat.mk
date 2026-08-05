################################################################################
#
# Tater protocol compatibility schema
#
# The upstream package supplies generated voice protobuf/model definitions.
# Its TCP client, discovery, reconnect, encryption, and CLI surfaces are not
# selected or shipped in this firmware.
#
################################################################################

PYTHON_TATER_PROTOCOL_COMPAT_VERSION = v42.7.0
PYTHON_TATER_PROTOCOL_COMPAT_SITE = https://github.com/esphome/aioesphomeapi.git
PYTHON_TATER_PROTOCOL_COMPAT_SITE_METHOD = git

PYTHON_TATER_PROTOCOL_COMPAT_SETUP_TYPE = setuptools
PYTHON_TATER_PROTOCOL_COMPAT_DEPENDENCIES = python-protobuf

define PYTHON_TATER_PROTOCOL_COMPAT_RENAME_MODULE
	rm -rf $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/tater_protocol_compat
	mv $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/aioesphomeapi \
		$(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/tater_protocol_compat
endef
PYTHON_TATER_PROTOCOL_COMPAT_POST_INSTALL_TARGET_HOOKS += PYTHON_TATER_PROTOCOL_COMPAT_RENAME_MODULE

$(eval $(python-package))
