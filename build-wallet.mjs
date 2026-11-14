import { build } from 'esbuild';
import { nodeModulesPolyfillPlugin } from 'esbuild-plugins-node-modules-polyfill';

await build({
  entryPoints: ['wallet/wallet-bridge.js'],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  outfile: 'static/wallet-bridge.bundle.js',
  define: {'process.env.NODE_ENV': '"production"'},
  plugins: [nodeModulesPolyfillPlugin({globals:{process:true,Buffer:true}})],
});
console.log('AVORA Meteor NEAR testnet wallet bundle built.');
