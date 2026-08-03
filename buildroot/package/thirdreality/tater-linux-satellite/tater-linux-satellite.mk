################################################################################
#
# tater-linux-satellite
#
################################################################################

# Keep this immutable. Use script/update_tater_linux_source.sh to advance it.
TATER_LINUX_SATELLITE_VERSION = 88b02994baf1843cb529d12d0cf5e54f39be61aa
TATER_LINUX_SATELLITE_SITE = $(call github,TaterTotterson,Tater-Linux-Satellite,$(TATER_LINUX_SATELLITE_VERSION))
TATER_LINUX_SATELLITE_LICENSE = Apache-2.0
TATER_LINUX_SATELLITE_LICENSE_FILES = LICENSE
TATER_LINUX_SATELLITE_SETUP_TYPE = pep517

TATER_LINUX_SATELLITE_DEPENDENCIES = \
	host-python-setuptools-scm \
	python-aioesphomeapi \
	python-getmac \
	python-mpv \
	python-netifaces-2 \
	python-numpy \
	pyopen-wakeword \
	python-pymicro-wakeword \
	python-soundcard \
	python-websockets \
	python-webrtc-noise-gain

# GitHub source archives do not contain .git metadata. Give setuptools-scm a
# deterministic PEP 440 version while keeping the full source SHA above.
TATER_LINUX_SATELLITE_ENV = SETUPTOOLS_SCM_PRETEND_VERSION=1.1.12.post23

TATER_LINUX_SATELLITE_PYTHON_SITE = $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages
TATER_LINUX_SATELLITE_PKGDIR = $(TOPDIR)/package/thirdreality/tater-linux-satellite

define TATER_LINUX_SATELLITE_INSTALL_RESOURCES
	mkdir -p $(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords
	mkdir -p $(TATER_LINUX_SATELLITE_PYTHON_SITE)/sounds
	cp -a $(@D)/wakewords/. $(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords/
	cp -a $(@D)/sounds/. $(TATER_LINUX_SATELLITE_PYTHON_SITE)/sounds/
	printf '%s\n' 'tater-thirdreality-$(TATER_LINUX_SATELLITE_VERSION)' > \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/version.txt
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-satellite-launcher \
		$(TARGET_DIR)/usr/bin/tater-satellite
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-configure \
		$(TARGET_DIR)/usr/bin/tater-configure
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-thirdreality-bridge.py \
		$(TARGET_DIR)/usr/bin/tater-thirdreality-bridge
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-provisioning \
		$(TARGET_DIR)/usr/bin/tater-provisioning
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-provisioning-server.py \
		$(TARGET_DIR)/usr/bin/tater-provisioning-server
	$(INSTALL) -D -m 0600 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater.json \
		$(TARGET_DIR)/usr/share/tater/defaults/tater.json
endef
TATER_LINUX_SATELLITE_POST_INSTALL_TARGET_HOOKS += TATER_LINUX_SATELLITE_INSTALL_RESOURCES

$(eval $(python-package))
