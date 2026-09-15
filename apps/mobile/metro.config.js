const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const path = require("path");

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "../..");

const config = getDefaultConfig(projectRoot);

// Monorepo support: Metro needs to watch the workspace root (so it picks
// up changes in packages/ui-tokens) and resolve modules hoisted there.
config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];
// pnpm's default linking is symlinked, not flat — even with node-linker=
// hoisted in .npmrc, Metro's own symlink resolution needs to be enabled
// explicitly for a monorepo layout.
config.resolver.unstable_enableSymlinks = true;

module.exports = withNativeWind(config, { input: "./global.css" });
