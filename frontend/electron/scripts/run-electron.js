const { spawn } = require('node:child_process');
const path = require('node:path');

const electronBinary = require('electron');
const args = process.argv.slice(2);
const env = { ...process.env };

delete env.ELECTRON_RUN_AS_NODE;

for (const arg of args) {
  if (arg.startsWith('--ui=')) {
    env.PULSE_UI_PATH = path.resolve(__dirname, '..', arg.slice('--ui='.length));
  }
}

const child = spawn(electronBinary, ['.'], {
  cwd: path.resolve(__dirname, '..'),
  env,
  stdio: 'inherit'
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

