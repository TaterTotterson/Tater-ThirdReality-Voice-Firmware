################################################################################
#
# Tater S420 satellite firmware
#
################################################################################

TATER_S420_FIRMWARE_VERSION = 0.2.4
TATER_S420_FIRMWARE_SITE = $(TOPDIR)/package/thirdreality/tater-s420-firmware
TATER_S420_FIRMWARE_SITE_METHOD = local

TATER_S420_FIRMWARE_INSTALL_TARGET = YES
TATER_S420_FIRMWARE_DEPENDENCIES = tater-linux-satellite

REALITY_DIR = $(TARGET_DIR)/usr/share/thirdreality

ifdef SPEAKER_FIRMWARE_VERSION
	IMAGE_VERSION=$(SPEAKER_FIRMWARE_VERSION)
else
	IMAGE_VERSION=$(shell date "+0.%m.%d")
endif

define TATER_S420_FIRMWARE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/device.json ${REALITY_DIR}/conf/device.json
	
	$(INSTALL) -D -m 0644 $(@D)/audio/setup_mode.wav ${REALITY_DIR}/audio/setup_mode.wav
	$(INSTALL) -D -m 0644 $(@D)/audio/change_wifi.wav ${REALITY_DIR}/audio/change_wifi.wav
	$(INSTALL) -D -m 0644 $(@D)/audio/not_ready.wav ${REALITY_DIR}/audio/not_ready.wav
	$(INSTALL) -D -m 0644 $(@D)/audio/factory_reset.wav ${REALITY_DIR}/audio/factory_reset.wav

	$(INSTALL) -D -m 0755 $(@D)/script/setup_env.sh ${REALITY_DIR}/script/setup_env.sh
	$(INSTALL) -D -m 0755 $(@D)/script/wifi_connect ${REALITY_DIR}/script/wifi_connect
	$(INSTALL) -D -m 0755 $(@D)/script/netmonitor ${REALITY_DIR}/script/netmonitor
	$(INSTALL) -D -m 0755 $(@D)/script/S99tater-satellite $(TARGET_DIR)/etc/init.d/S99tater-satellite
	printf '%s\n' 'tater-thirdreality-$(IMAGE_VERSION)' > \
		$(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/version.txt

	@echo "firmwareVersion is $(IMAGE_VERSION)"
	@jq '.device.firmwareVersion = "$(IMAGE_VERSION)"' $(TARGET_DIR)/usr/share/thirdreality/conf/device.json > \
		tmp.$$.json && mv tmp.$$.json $(TARGET_DIR)/usr/share/thirdreality/conf/device.json

endef

$(eval $(generic-package))
