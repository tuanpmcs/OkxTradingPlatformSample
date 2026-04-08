const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('streamApi', {
  start: (config) => ipcRenderer.invoke('stream:start', config),
  stop: () => ipcRenderer.invoke('stream:stop'),
  predict: (payload) => ipcRenderer.invoke('prediction:infer', payload),
  onData: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('stream:data', listener);
    return () => ipcRenderer.removeListener('stream:data', listener);
  },
  onDataBatch: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('stream:data-batch', listener);
    return () => ipcRenderer.removeListener('stream:data-batch', listener);
  },
  onStatus: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('stream:status', listener);
    return () => ipcRenderer.removeListener('stream:status', listener);
  }
});
