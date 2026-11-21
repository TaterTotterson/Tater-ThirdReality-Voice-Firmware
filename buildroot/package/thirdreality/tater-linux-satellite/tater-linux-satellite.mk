################################################################################
#
# tater-linux-satellite
#
################################################################################

# Keep this immutable. Review hardware compatibility before advancing it.
# Shared wake/audio/native features come directly from this published revision;
# 0001 contains only S420 hardware and firmware packaging changes.
TATER_LINUX_SATELLITE_VERSION = b07b567faf848576a8b1e8db6b91b946bf6ef51b
TATER_LINUX_SATELLITE_SITE = $(call github,TaterTotterson,Tater-Linux-Satellite,$(TATER_LINUX_SATELLITE_VERSION))
TATER_LINUX_SATELLITE_LICENSE = Apache-2.0
TATER_LINUX_SATELLITE_LICENSE_FILES = LICENSE.md
TATER_LINUX_SATELLITE_SETUP_TYPE = pep517

TATER_LINUX_SATELLITE_DEPENDENCIES = \
	bluez5-utils \
	python-bleak \
	onnxruntime-aarch64 \
	python-tater-protocol-compat \
	python-getmac \
	python-mpv \
	python-netifaces-2 \
	python-numpy \
	pyopen-wakeword \
	python-pymicro-wakeword \
	python-soundcard \
	python-websockets \
	python-webrtc-noise-gain

TATER_LINUX_SATELLITE_PYTHON_SITE = $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages
TATER_LINUX_SATELLITE_PKGDIR = $(TOPDIR)/package/thirdreality/tater-linux-satellite

# The pinned upstream runtime still names the voice protobuf schema after its
# historical transport. This production build uses a private Tater-only module
# name and removes legacy product terminology before compiling the wheel.
define TATER_LINUX_SATELLITE_USE_TATER_PROTOCOL_COMPAT
	$(SED) 's/aioesphomeapi/tater_protocol_compat/g' \
		$(@D)/linux_voice_assistant/*.py
	$(SED) 's/get_esphome_version/get_protocol_compat_version/g; s/esphome_version/protocol_compat_version/g' \
		$(@D)/linux_voice_assistant/*.py
	$(SED) 's/ESPHomeEntity/TaterEntity/g; s/ESPHome/legacy API/g; s/Home Assistant/legacy controller/g' \
		$(@D)/linux_voice_assistant/*.py
	$(SED) 's/Resolve esphome version/Resolve protocol compatibility version/g; s/COMMANDS FROM HOME ASSISTANT/COMMANDS FROM TATER/g' \
		$(@D)/linux_voice_assistant/*.py
endef
TATER_LINUX_SATELLITE_POST_PATCH_HOOKS += TATER_LINUX_SATELLITE_USE_TATER_PROTOCOL_COMPAT

define TATER_LINUX_SATELLITE_BUILD_OWW_BRIDGE
	$(TARGET_CC) $(TARGET_CFLAGS) -O2 -fPIC -shared \
		-I$(STAGING_DIR)/usr/include/onnxruntime \
		$(TATER_LINUX_SATELLITE_PKGDIR)/files/tater_oww_ort.c \
		-ldl -lm -o $(@D)/libtater_oww_ort.so
endef
TATER_LINUX_SATELLITE_POST_BUILD_HOOKS += TATER_LINUX_SATELLITE_BUILD_OWW_BRIDGE

define TATER_LINUX_SATELLITE_INSTALL_RESOURCES
	rm -f $(TARGET_DIR)/etc/init.d/S44bluetooth
	mkdir -p $(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords
	mkdir -p $(TATER_LINUX_SATELLITE_PYTHON_SITE)/sounds
	mkdir -p $(TARGET_DIR)/usr/share/tater/openwakeword
	cp -a $(@D)/wakewords/. $(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords/
	cp -a $(@D)/sounds/. $(TATER_LINUX_SATELLITE_PYTHON_SITE)/sounds/
	cp -a $(TATER_LINUX_SATELLITE_PKGDIR)/files/wake_sounds/. \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/sounds/
	$(INSTALL) -D -m 0644 $(TATER_LINUX_SATELLITE_PKGDIR)/files/wakewords/hey_tater.json \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords/hey_tater.json
	$(INSTALL) -D -m 0644 $(TATER_LINUX_SATELLITE_PKGDIR)/files/wakewords/hey_tater.tflite \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords/hey_tater.tflite
	find $(TATER_LINUX_SATELLITE_PYTHON_SITE)/wakewords -type f \
		\( -name 'hey_home_assistant.*' -o -iname '*nabu*' \) -delete
	$(INSTALL) -D -m 0644 $(@D)/linux_voice_assistant/tater_features.py \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/linux_voice_assistant/shared_features.py
	$(INSTALL) -D -m 0644 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater_features.py \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/linux_voice_assistant/tater_features.py
	$(INSTALL) -D -m 0755 $(@D)/libtater_oww_ort.so \
		$(TARGET_DIR)/usr/lib/libtater_oww_ort.so
	cp -a $(TATER_LINUX_SATELLITE_PKGDIR)/files/openwakeword/. \
		$(TARGET_DIR)/usr/share/tater/openwakeword/
	$(INSTALL) -D -m 0644 $(TATER_LINUX_SATELLITE_PKGDIR)/files/s420_audio.py \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/linux_voice_assistant/s420_audio.py
	printf '%s\n' 'tater-thirdreality-$(TATER_LINUX_SATELLITE_VERSION)' > \
		$(TATER_LINUX_SATELLITE_PYTHON_SITE)/version.txt
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-satellite-launcher \
		$(TARGET_DIR)/usr/bin/tater-satellite
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-s420-audio-diagnostic \
		$(TARGET_DIR)/usr/bin/tater-s420-audio-diagnostic
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-configure \
		$(TARGET_DIR)/usr/bin/tater-configure
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-thirdreality-bridge.py \
		$(TARGET_DIR)/usr/bin/tater-thirdreality-bridge
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-provisioning \
		$(TARGET_DIR)/usr/bin/tater-provisioning
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater-provisioning-server.py \
		$(TARGET_DIR)/usr/bin/tater-provisioning-server
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/S38tater-network-persistence \
		$(TARGET_DIR)/etc/init.d/S38tater-network-persistence
	$(INSTALL) -D -m 0755 $(TATER_LINUX_SATELLITE_PKGDIR)/files/S44tater-bluetooth \
		$(TARGET_DIR)/etc/init.d/S44tater-bluetooth
	$(INSTALL) -D -m 0600 $(TATER_LINUX_SATELLITE_PKGDIR)/files/tater.json \
		$(TARGET_DIR)/usr/share/tater/defaults/tater.json
endef
TATER_LINUX_SATELLITE_POST_INSTALL_TARGET_HOOKS += TATER_LINUX_SATELLITE_INSTALL_RESOURCES

$(eval $(python-package))
