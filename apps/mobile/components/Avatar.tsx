import { Image, Text, View } from "react-native";

import { avatarColorFor, initialsFor } from "../lib/avatar-color";
import { useTheme } from "../lib/theme-context";

interface AvatarProps {
  name: string;
  id: string;
  imageUrl?: string | null;
  size?: number;
  ring?: boolean;
}

/** A photo when there is one, otherwise a colored circle with initials
 * (lib/avatar-color.ts — deterministic per id, not random per render).
 * `ring` draws a thin accent ring around it — used for online/active or
 * Circle-trusted indicators by callers, not decided here. */
export function Avatar({ name, id, imageUrl, size = 44, ring = false }: AvatarProps) {
  const { colors } = useTheme();
  const color = avatarColorFor(id);
  const fontSize = Math.max(11, size * 0.38);

  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: imageUrl ? colors.surfaceRaised : color,
        borderWidth: ring ? 2 : 0,
        borderColor: colors.accent,
      }}
    >
      {imageUrl ? (
        <Image
          source={{ uri: imageUrl }}
          style={{ width: size, height: size, borderRadius: size / 2 }}
        />
      ) : (
        <Text style={{ fontSize, fontWeight: "700", color: "#0B0B12" }}>{initialsFor(name)}</Text>
      )}
    </View>
  );
}
