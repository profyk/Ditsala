import { View } from "react-native";

export type IconName =
  | "home"
  | "messages"
  | "circle"
  | "settings"
  | "chevron-right"
  | "chevron-left"
  | "chevron-down"
  | "plus"
  | "close"
  | "check"
  | "search"
  | "phone"
  | "video"
  | "camera"
  | "send"
  | "bell"
  | "shield"
  | "location"
  | "logout"
  | "edit"
  | "more"
  | "lock"
  | "mic"
  | "sun"
  | "moon";

interface IconProps {
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}

/**
 * A small, dependency-free vector icon set built from View primitives
 * (borders, rotation, overlap) — not @expo/vector-icons or react-native-
 * svg. Deliberate: this machine has repeatedly run out of disk mid-
 * install this session (see git history around the same date), and a
 * font-bundling icon package is exactly the kind of install that tips
 * it over. Every icon here is geometric and monochrome by construction
 * (a stroke-width square/circle/line composition, styled via `color`),
 * matching the "no bubble/playful chrome" brand instinct even after the
 * rest of the visual identity moved on. Covers what the redesigned tab
 * bar and core screens need — not a general-purpose icon library.
 */
export function Icon({ name, size = 24, color = "#FFFFFF", strokeWidth = 2 }: IconProps) {
  const s = size;
  const sw = strokeWidth;

  switch (name) {
    case "home":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "flex-end" }}>
          <View
            style={{
              position: "absolute",
              top: s * 0.42,
              width: s * 0.58,
              height: s * 0.58,
              transform: [{ rotate: "45deg" }],
              borderWidth: sw,
              borderColor: color,
              borderRadius: 3,
            }}
          />
          <View
            style={{
              width: s * 0.36,
              height: s * 0.36,
              borderTopWidth: sw,
              borderLeftWidth: sw,
              borderRightWidth: sw,
              borderColor: color,
              borderTopLeftRadius: s * 0.18,
              borderTopRightRadius: s * 0.18,
              transform: [{ rotate: "45deg" }],
            }}
          />
        </View>
      );

    case "messages":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.82,
              height: s * 0.6,
              borderWidth: sw,
              borderColor: color,
              borderRadius: s * 0.16,
            }}
          />
          <View
            style={{
              position: "absolute",
              bottom: s * 0.06,
              left: s * 0.24,
              width: s * 0.18,
              height: s * 0.18,
              backgroundColor: color,
              transform: [{ rotate: "45deg" }],
            }}
          />
        </View>
      );

    case "circle":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              position: "absolute",
              left: s * 0.14,
              width: s * 0.44,
              height: s * 0.44,
              borderRadius: 999,
              borderWidth: sw,
              borderColor: color,
            }}
          />
          <View
            style={{
              position: "absolute",
              right: s * 0.14,
              width: s * 0.44,
              height: s * 0.44,
              borderRadius: 999,
              borderWidth: sw,
              borderColor: color,
            }}
          />
        </View>
      );

    case "settings":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.7,
              height: s * 0.7,
              borderRadius: 999,
              borderWidth: sw,
              borderColor: color,
            }}
          />
          <View
            style={{
              position: "absolute",
              width: s * 0.22,
              height: s * 0.22,
              borderRadius: 999,
              backgroundColor: color,
            }}
          />
        </View>
      );

    case "chevron-right":
    case "chevron-left":
    case "chevron-down": {
      const rotate = name === "chevron-right" ? "-45deg" : name === "chevron-left" ? "135deg" : "-135deg";
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.4,
              height: s * 0.4,
              borderTopWidth: sw,
              borderRightWidth: sw,
              borderColor: color,
              transform: [{ rotate }],
            }}
          />
        </View>
      );
    }

    case "plus":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View style={{ position: "absolute", width: s * 0.6, height: sw, backgroundColor: color, borderRadius: sw / 2 }} />
          <View style={{ position: "absolute", width: sw, height: s * 0.6, backgroundColor: color, borderRadius: sw / 2 }} />
        </View>
      );

    case "close":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              position: "absolute",
              width: s * 0.6,
              height: sw,
              backgroundColor: color,
              borderRadius: sw / 2,
              transform: [{ rotate: "45deg" }],
            }}
          />
          <View
            style={{
              position: "absolute",
              width: s * 0.6,
              height: sw,
              backgroundColor: color,
              borderRadius: sw / 2,
              transform: [{ rotate: "-45deg" }],
            }}
          />
        </View>
      );

    case "check":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.5,
              height: s * 0.28,
              borderLeftWidth: sw,
              borderBottomWidth: sw,
              borderColor: color,
              transform: [{ rotate: "-45deg" }],
              marginTop: -s * 0.06,
            }}
          />
        </View>
      );

    case "search":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              position: "absolute",
              top: s * 0.16,
              left: s * 0.16,
              width: s * 0.5,
              height: s * 0.5,
              borderRadius: 999,
              borderWidth: sw,
              borderColor: color,
            }}
          />
          <View
            style={{
              position: "absolute",
              bottom: s * 0.12,
              right: s * 0.12,
              width: s * 0.28,
              height: sw,
              backgroundColor: color,
              borderRadius: sw / 2,
              transform: [{ rotate: "45deg" }],
            }}
          />
        </View>
      );

    case "phone":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.5,
              height: s * 0.5,
              borderWidth: sw,
              borderColor: color,
              borderRadius: s * 0.22,
              borderBottomLeftRadius: 2,
              transform: [{ rotate: "-45deg" }],
            }}
          />
        </View>
      );

    case "video":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center", flexDirection: "row" }}>
          <View
            style={{
              width: s * 0.5,
              height: s * 0.4,
              borderWidth: sw,
              borderColor: color,
              borderRadius: s * 0.08,
            }}
          />
          <View
            style={{
              width: 0,
              height: 0,
              marginLeft: 2,
              borderTopWidth: s * 0.14,
              borderBottomWidth: s * 0.14,
              borderLeftWidth: s * 0.2,
              borderTopColor: "transparent",
              borderBottomColor: "transparent",
              borderLeftColor: color,
            }}
          />
        </View>
      );

    case "camera":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.7,
              height: s * 0.52,
              borderWidth: sw,
              borderColor: color,
              borderRadius: s * 0.1,
            }}
          />
          <View
            style={{
              position: "absolute",
              width: s * 0.24,
              height: s * 0.24,
              borderRadius: 999,
              borderWidth: sw,
              borderColor: color,
            }}
          />
        </View>
      );

    case "send":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: 0,
              height: 0,
              borderTopWidth: s * 0.32,
              borderBottomWidth: s * 0.32,
              borderLeftWidth: s * 0.5,
              borderTopColor: "transparent",
              borderBottomColor: "transparent",
              borderLeftColor: color,
              transform: [{ rotate: "0deg" }],
            }}
          />
        </View>
      );

    case "bell":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.5,
              height: s * 0.46,
              borderWidth: sw,
              borderColor: color,
              borderTopLeftRadius: s * 0.25,
              borderTopRightRadius: s * 0.25,
              borderBottomWidth: 0,
            }}
          />
          <View style={{ width: s * 0.62, height: sw, backgroundColor: color, marginTop: -sw, borderRadius: sw / 2 }} />
        </View>
      );

    case "shield":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.56,
              height: s * 0.66,
              borderWidth: sw,
              borderColor: color,
              borderTopLeftRadius: s * 0.28,
              borderTopRightRadius: s * 0.28,
              borderBottomLeftRadius: s * 0.05,
              borderBottomRightRadius: s * 0.05,
            }}
          />
        </View>
      );

    case "location":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.48,
              height: s * 0.48,
              borderRadius: 999,
              borderTopLeftRadius: 999,
              borderTopRightRadius: 999,
              borderBottomRightRadius: 999,
              borderWidth: sw,
              borderColor: color,
              transform: [{ rotate: "-45deg" }],
              borderBottomLeftRadius: 0,
            }}
          />
        </View>
      );

    case "logout":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.4,
              height: s * 0.6,
              borderWidth: sw,
              borderColor: color,
              borderRightWidth: 0,
              borderTopLeftRadius: s * 0.08,
              borderBottomLeftRadius: s * 0.08,
            }}
          />
          <View style={{ position: "absolute", right: s * 0.16, width: s * 0.32, height: sw, backgroundColor: color }} />
        </View>
      );

    case "edit":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.56,
              height: sw * 1.6,
              backgroundColor: color,
              borderRadius: sw,
              transform: [{ rotate: "-45deg" }],
            }}
          />
        </View>
      );

    case "more":
      return (
        <View style={{ width: s, height: s, flexDirection: "row", alignItems: "center", justifyContent: "space-evenly" }}>
          <View style={{ width: sw * 1.6, height: sw * 1.6, borderRadius: 999, backgroundColor: color }} />
          <View style={{ width: sw * 1.6, height: sw * 1.6, borderRadius: 999, backgroundColor: color }} />
          <View style={{ width: sw * 1.6, height: sw * 1.6, borderRadius: 999, backgroundColor: color }} />
        </View>
      );

    case "lock":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              position: "absolute",
              top: s * 0.14,
              width: s * 0.32,
              height: s * 0.28,
              borderWidth: sw,
              borderColor: color,
              borderBottomWidth: 0,
              borderTopLeftRadius: s * 0.2,
              borderTopRightRadius: s * 0.2,
            }}
          />
          <View
            style={{
              width: s * 0.5,
              height: s * 0.4,
              backgroundColor: color,
              borderRadius: s * 0.08,
              marginTop: s * 0.2,
            }}
          />
        </View>
      );

    case "mic":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View style={{ width: s * 0.28, height: s * 0.48, backgroundColor: color, borderRadius: s * 0.14 }} />
          <View
            style={{
              position: "absolute",
              bottom: s * 0.12,
              width: s * 0.5,
              height: s * 0.3,
              borderWidth: sw,
              borderTopWidth: 0,
              borderColor: color,
              borderBottomLeftRadius: s * 0.25,
              borderBottomRightRadius: s * 0.25,
            }}
          />
        </View>
      );

    case "sun":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          {[0, 45, 90, 135].map((deg) => (
            <View
              key={deg}
              style={{
                position: "absolute",
                width: s * 0.72,
                height: sw,
                backgroundColor: color,
                borderRadius: sw / 2,
                transform: [{ rotate: `${deg}deg` }],
              }}
            />
          ))}
          <View
            style={{
              width: s * 0.36,
              height: s * 0.36,
              borderRadius: 999,
              backgroundColor: color,
            }}
          />
        </View>
      );

    case "moon":
      return (
        <View style={{ width: s, height: s, alignItems: "center", justifyContent: "center" }}>
          <View
            style={{
              width: s * 0.62,
              height: s * 0.62,
              borderRadius: 999,
              borderWidth: sw * 1.3,
              borderColor: color,
              borderLeftColor: "transparent",
              borderBottomColor: "transparent",
              transform: [{ rotate: "45deg" }],
            }}
          />
        </View>
      );

    default:
      return <View style={{ width: s, height: s }} />;
  }
}
