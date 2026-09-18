import { CameraView, useCameraPermissions, type BarcodeScanningResult } from "expo-camera";
import * as Linking from "expo-linking";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Share, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError, authApi } from "../../lib/api";
import { circleApi } from "../../lib/circle-api";
import { extractContactUserId } from "../../lib/circle-link";
import { getAccessToken } from "../../lib/session";

/**
 * §22: relationship establishment via QR scan or invite link — both are
 * the same underlying `ditsala://circle/add?userId=<id>` link, QR is just
 * that link encoded as an image. This app can scan a QR encoding that
 * link (expo-camera's barcode scanner) and can share the link itself
 * (native Share sheet), but doesn't render its own QR code image yet —
 * that needs a QR-generation library, deliberately not added here to
 * avoid a new native dependency on this memory-constrained dev machine.
 * See docs/SECURITY_GAPS.md.
 */
export default function AddToCircle() {
  const router = useRouter();
  const { userId: incomingUserId } = useLocalSearchParams<{ userId?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const sendRequest = useCallback(
    async (targetUserId: string, channel: "qr" | "invite_link") => {
      const token = await getAccessToken();
      if (!token) {
        router.replace("/");
        return;
      }
      setBusy(true);
      setError(null);
      try {
        await circleApi.sendContactRequest(token, targetUserId, channel);
        setSent(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not send the request.");
      } finally {
        setBusy(false);
        setScanning(false);
      }
    },
    [router]
  );

  useEffect(() => {
    if (incomingUserId) {
      sendRequest(incomingUserId, "invite_link");
    }
  }, [incomingUserId, sendRequest]);

  async function handleShare() {
    const token = await getAccessToken();
    if (!token) return;
    setError(null);
    try {
      const me = await authApi.getMe(token);
      const link = Linking.createURL("/circle/add", { queryParams: { userId: me.id } });
      await Share.share({ message: `Add me on DITSALA: ${link}` });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your Circle link.");
    }
  }

  async function handleStartScan() {
    if (!permission?.granted) {
      const result = await requestPermission();
      if (!result.granted) {
        setError("Camera access is needed to scan a Circle QR code.");
        return;
      }
    }
    setScanning(true);
  }

  function handleBarcodeScanned(result: BarcodeScanningResult) {
    const targetUserId = extractContactUserId(result.data);
    if (!targetUserId) {
      setError("That QR code isn't a DITSALA Circle code.");
      setScanning(false);
      return;
    }
    sendRequest(targetUserId, "qr");
  }

  if (sent) {
    return (
      <Screen>
        <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Request sent</Text>
        <Text className="mb-8 text-base text-text-secondary">
          They&apos;ll need to accept before you can message each other.
        </Text>
        <Button label="Done" onPress={() => router.replace("/circle")} />
      </Screen>
    );
  }

  if (scanning) {
    return (
      <View className="flex-1 bg-background">
        <CameraView
          className="flex-1"
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={busy ? undefined : handleBarcodeScanned}
        />
        <View className="absolute bottom-12 left-6 right-6">
          {error ? <Text className="mb-4 text-center text-sm text-danger">{error}</Text> : null}
          <Button label="Cancel" variant="secondary" onPress={() => setScanning(false)} />
        </View>
      </View>
    );
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Add to Circle</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Find people you know, scan someone&apos;s Circle QR code, or share your own link.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="find-contacts-nav-button"
        label="Find contacts on DITSALA"
        icon="search"
        onPress={() => router.push("/circle/find-contacts")}
      />
      <View className="h-3" />
      <Button
        testID="scan-qr-button"
        label="Scan a QR code"
        variant="secondary"
        onPress={handleStartScan}
        loading={busy}
      />
      <View className="h-3" />
      <Button
        testID="share-link-button"
        label="Share my Circle link"
        variant="secondary"
        onPress={handleShare}
      />
    </Screen>
  );
}
