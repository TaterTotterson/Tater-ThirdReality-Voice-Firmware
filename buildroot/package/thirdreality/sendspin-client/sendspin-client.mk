################################################################################
#
# sendspin-client
#
################################################################################

# Pin the official CLI and every FetchContent input so firmware builds do not
# depend on moving branches or network access during the CMake configure step.
SENDSPIN_CLIENT_VERSION = 05f99441f6a1255a1becf3cf4ab65eead11d63d8
SENDSPIN_CLIENT_SITE = $(call github,Sendspin,sendspin-cpp-cli,$(SENDSPIN_CLIENT_VERSION))
SENDSPIN_CLIENT_PKGDIR = $(TOPDIR)/package/thirdreality/sendspin-client
SENDSPIN_CLIENT_LICENSE = Apache-2.0, MIT, BSD-3-Clause
SENDSPIN_CLIENT_LICENSE_FILES = \
	LICENSE \
	deps/sendspin/LICENSE \
	deps/arduinojson/LICENSE.txt \
	deps/micro-flac/LICENSE \
	deps/ixwebsocket/LICENSE.txt \
	deps/noise-c/COPYING \
	deps/noise-c/LICENSE

SENDSPIN_CLIENT_SENDSPIN_VERSION = 1d9ef34a97e5422ce634b162910e60001d213ced
SENDSPIN_CLIENT_ARDUINOJSON_VERSION = 7.4.1
SENDSPIN_CLIENT_MICRO_FLAC_VERSION = 0.1.1
SENDSPIN_CLIENT_IXWEBSOCKET_VERSION = 12.0.1
SENDSPIN_CLIENT_NOISE_C_VERSION = 0.1.13

SENDSPIN_CLIENT_EXTRA_DOWNLOADS = \
	$(call github,Sendspin,sendspin-cpp,$(SENDSPIN_CLIENT_SENDSPIN_VERSION))/sendspin-cpp-$(SENDSPIN_CLIENT_SENDSPIN_VERSION).tar.gz \
	$(call github,bblanchon,ArduinoJson,v$(SENDSPIN_CLIENT_ARDUINOJSON_VERSION))/arduinojson-$(SENDSPIN_CLIENT_ARDUINOJSON_VERSION).tar.gz \
	$(call github,esphome-libs,micro-flac,v$(SENDSPIN_CLIENT_MICRO_FLAC_VERSION))/micro-flac-$(SENDSPIN_CLIENT_MICRO_FLAC_VERSION).tar.gz \
	$(call github,machinezone,IXWebSocket,v$(SENDSPIN_CLIENT_IXWEBSOCKET_VERSION))/ixwebsocket-$(SENDSPIN_CLIENT_IXWEBSOCKET_VERSION).tar.gz \
	$(call github,esphome-libs,noise-c,v$(SENDSPIN_CLIENT_NOISE_C_VERSION))/noise-c-$(SENDSPIN_CLIENT_NOISE_C_VERSION).tar.gz

SENDSPIN_CLIENT_DEPENDENCIES = avahi host-pkgconf pulseaudio

define SENDSPIN_CLIENT_EXTRACT_FETCHCONTENT
	mkdir -p $(@D)/deps/sendspin $(@D)/deps/arduinojson \
		$(@D)/deps/micro-flac $(@D)/deps/ixwebsocket $(@D)/deps/noise-c
	$(call suitable-extractor,sendspin-cpp-$(SENDSPIN_CLIENT_SENDSPIN_VERSION).tar.gz) \
		$(SENDSPIN_CLIENT_DL_DIR)/sendspin-cpp-$(SENDSPIN_CLIENT_SENDSPIN_VERSION).tar.gz | \
		$(TAR) --strip-components=1 -C $(@D)/deps/sendspin $(TAR_OPTIONS) -
	$(call suitable-extractor,arduinojson-$(SENDSPIN_CLIENT_ARDUINOJSON_VERSION).tar.gz) \
		$(SENDSPIN_CLIENT_DL_DIR)/arduinojson-$(SENDSPIN_CLIENT_ARDUINOJSON_VERSION).tar.gz | \
		$(TAR) --strip-components=1 -C $(@D)/deps/arduinojson $(TAR_OPTIONS) -
	$(call suitable-extractor,micro-flac-$(SENDSPIN_CLIENT_MICRO_FLAC_VERSION).tar.gz) \
		$(SENDSPIN_CLIENT_DL_DIR)/micro-flac-$(SENDSPIN_CLIENT_MICRO_FLAC_VERSION).tar.gz | \
		$(TAR) --strip-components=1 -C $(@D)/deps/micro-flac $(TAR_OPTIONS) -
	$(call suitable-extractor,ixwebsocket-$(SENDSPIN_CLIENT_IXWEBSOCKET_VERSION).tar.gz) \
		$(SENDSPIN_CLIENT_DL_DIR)/ixwebsocket-$(SENDSPIN_CLIENT_IXWEBSOCKET_VERSION).tar.gz | \
		$(TAR) --strip-components=1 -C $(@D)/deps/ixwebsocket $(TAR_OPTIONS) -
	$(call suitable-extractor,noise-c-$(SENDSPIN_CLIENT_NOISE_C_VERSION).tar.gz) \
		$(SENDSPIN_CLIENT_DL_DIR)/noise-c-$(SENDSPIN_CLIENT_NOISE_C_VERSION).tar.gz | \
		$(TAR) --strip-components=1 -C $(@D)/deps/noise-c $(TAR_OPTIONS) -
endef
SENDSPIN_CLIENT_POST_EXTRACT_HOOKS += SENDSPIN_CLIENT_EXTRACT_FETCHCONTENT

SENDSPIN_CLIENT_CONF_OPTS = \
	-DBUILD_SHARED_LIBS=OFF \
	-DSENDSPIN_GIT_TAG=$(SENDSPIN_CLIENT_SENDSPIN_VERSION) \
	-DFETCHCONTENT_SOURCE_DIR_SENDSPIN=$(@D)/deps/sendspin \
	-DFETCHCONTENT_SOURCE_DIR_ARDUINOJSON=$(@D)/deps/arduinojson \
	-DFETCHCONTENT_SOURCE_DIR_MICRO_FLAC=$(@D)/deps/micro-flac \
	-DFETCHCONTENT_SOURCE_DIR_IXWEBSOCKET=$(@D)/deps/ixwebsocket \
	-DFETCHCONTENT_SOURCE_DIR_NOISE_C=$(@D)/deps/noise-c \
	-DSENDSPIN_ENABLE_PLAYER=ON \
	-DSENDSPIN_ENABLE_METADATA=ON \
	-DSENDSPIN_ENABLE_CONTROLLER=ON \
	-DSENDSPIN_ENABLE_SOURCE=ON \
	-DSENDSPIN_ENABLE_COLOR=OFF \
	-DSENDSPIN_ENABLE_ARTWORK=OFF \
	-DSENDSPIN_ENABLE_VISUALIZER=OFF \
	-DSENDSPIN_ENABLE_OPUS=OFF \
	-DMICRO_FLAC_ENABLE_OGG=OFF \
	-DBUILD_EXAMPLES=OFF \
	-DSENDSPIN_CLI_BUILD_TESTS=OFF \
	-DSENDSPIN_CLI_WITH_ALSA=OFF \
	-DSENDSPIN_CLI_WITH_COREAUDIO=OFF \
	-DSENDSPIN_CLI_WITH_PORTAUDIO=OFF \
	-DSENDSPIN_CLI_WITH_PULSE=ON \
	-DSENDSPIN_CLI_WITH_PIPEWIRE=OFF \
	-DSENDSPIN_CLI_WITH_MDNS=ON

define SENDSPIN_CLIENT_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/sendspin-cli $(TARGET_DIR)/usr/bin/sendspin-cli
	$(INSTALL) -D -m 0755 $(SENDSPIN_CLIENT_PKGDIR)/files/tater-sendspin \
		$(TARGET_DIR)/usr/bin/tater-sendspin
	$(INSTALL) -D -m 0755 $(SENDSPIN_CLIENT_PKGDIR)/files/tater-sendspin-hook \
		$(TARGET_DIR)/usr/bin/tater-sendspin-hook
endef

$(eval $(cmake-package))
