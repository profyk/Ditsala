import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Image, Pressable, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { accountApi } from "../../lib/account-api";
import { ApiError, authApi, type CurrentUser } from "../../lib/api";
import { getAccessToken } from "../../lib/session";

/**
 * Profile picture management (docs/DITSALA_MASTER_SPEC.md §3 reuse —
 * the same presigned-URL StorageProvider flow media uploads already
 * use). Not E2EE, deliberately: a profile picture is meant to be
 * visible to your Circle, unlike message content.
 */
export default function Profile() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function load() {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      setUser(await authApi.getMe(token));
    } catch {
      setError("Could not load your profile.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handlePickAndUpload() {
    setError(null);
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setError("Photo library access is needed to set a profile picture.");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });
    if (result.canceled || result.assets.length === 0) return;

    const asset = result.assets[0];
    const contentType = asset.mimeType ?? "image/jpeg";
    const token = await getAccessToken();
    if (!token) return;

    setUploading(true);
    try {
      const { key, upload_url } = await accountApi.requestAvatarUpload(token, contentType);
      const fileResponse = await fetch(asset.uri);
      const fileBlob = await fileResponse.blob();
      const putResponse = await fetch(upload_url, {
        method: "PUT",
        body: fileBlob,
        headers: { "Content-Type": contentType },
      });
      if (!putResponse.ok) throw new Error("Upload failed.");
      await accountApi.confirmAvatar(token, key);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update your profile picture.");
    } finally {
      setUploading(false);
    }
  }

  async function handleRemove() {
    const token = await getAccessToken();
    if (!token) return;
    setUploading(true);
    try {
      await accountApi.removeAvatar(token);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove your profile picture.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-6 mt-8 text-3xl font-semibold text-text-primary">Profile</Text>

      <View className="items-center">
        <Pressable
          testID="profile-avatar"
          onPress={handlePickAndUpload}
          disabled={uploading}
          className="mb-4 h-28 w-28 items-center justify-center overflow-hidden rounded-full border border-border bg-surface"
        >
          {user?.avatar_url ? (
            <Image source={{ uri: user.avatar_url }} className="h-28 w-28" />
          ) : (
            <Text className="text-4xl font-semibold text-text-tertiary">
              {(user?.display_name ?? "?").charAt(0).toUpperCase()}
            </Text>
          )}
        </Pressable>
        <Text className="mb-1 text-xl font-semibold text-text-primary">{user?.display_name}</Text>
        <Text className="mb-6 text-sm text-text-tertiary">Tap your photo to change it</Text>
      </View>

      {error ? <Text className="mb-4 text-center text-sm text-danger">{error}</Text> : null}

      <Button
        testID="change-photo-button"
        label="Change photo"
        onPress={handlePickAndUpload}
        loading={uploading}
      />
      {user?.avatar_url ? (
        <>
          <View className="h-3" />
          <Button
            testID="remove-photo-button"
            label="Remove photo"
            variant="secondary"
            onPress={handleRemove}
            disabled={uploading}
          />
        </>
      ) : null}
    </Screen>
  );
}
