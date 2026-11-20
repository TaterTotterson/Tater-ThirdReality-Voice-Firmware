################################################################################
#
# onnxruntime-aarch64
#
################################################################################

ONNXRUNTIME_AARCH64_VERSION = 1.22.0
ONNXRUNTIME_AARCH64_SOURCE = onnxruntime-linux-aarch64-$(ONNXRUNTIME_AARCH64_VERSION).tgz
# Keep the original, hash-verified archive available when the upstream asset is unavailable.
ONNXRUNTIME_AARCH64_SITE = file://$(TOPDIR)/package/thirdreality/onnxruntime-aarch64
ONNXRUNTIME_AARCH64_SITE_METHOD = file
ONNXRUNTIME_AARCH64_LICENSE = MIT
ONNXRUNTIME_AARCH64_LICENSE_FILES = LICENSE ThirdPartyNotices.txt
ONNXRUNTIME_AARCH64_INSTALL_STAGING = YES

define ONNXRUNTIME_AARCH64_INSTALL_STAGING_CMDS
	mkdir -p $(STAGING_DIR)/usr/include/onnxruntime $(STAGING_DIR)/usr/lib
	cp -a $(@D)/include/. $(STAGING_DIR)/usr/include/onnxruntime/
	$(INSTALL) -D -m 0755 $(@D)/lib/libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION) \
		$(STAGING_DIR)/usr/lib/libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION)
	ln -sf libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION) $(STAGING_DIR)/usr/lib/libonnxruntime.so.1
	ln -sf libonnxruntime.so.1 $(STAGING_DIR)/usr/lib/libonnxruntime.so
endef

define ONNXRUNTIME_AARCH64_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/lib/libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION) \
		$(TARGET_DIR)/usr/lib/libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION)
	ln -sf libonnxruntime.so.$(ONNXRUNTIME_AARCH64_VERSION) $(TARGET_DIR)/usr/lib/libonnxruntime.so.1
	ln -sf libonnxruntime.so.1 $(TARGET_DIR)/usr/lib/libonnxruntime.so
endef

$(eval $(generic-package))
