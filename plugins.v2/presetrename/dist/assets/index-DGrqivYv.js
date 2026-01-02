import { importShared } from './__federation_fn_import-BmTa56O4.js';
import Config from './__federation_expose_Config-DkLNyfqy.js';

true&&(function polyfill() {
  const relList = document.createElement("link").relList;
  if (relList && relList.supports && relList.supports("modulepreload")) {
    return;
  }
  for (const link of document.querySelectorAll('link[rel="modulepreload"]')) {
    processPreload(link);
  }
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "childList") {
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node.tagName === "LINK" && node.rel === "modulepreload")
          processPreload(node);
      }
    }
  }).observe(document, { childList: true, subtree: true });
  function getFetchOpts(link) {
    const fetchOpts = {};
    if (link.integrity) fetchOpts.integrity = link.integrity;
    if (link.referrerPolicy) fetchOpts.referrerPolicy = link.referrerPolicy;
    if (link.crossOrigin === "use-credentials")
      fetchOpts.credentials = "include";
    else if (link.crossOrigin === "anonymous") fetchOpts.credentials = "omit";
    else fetchOpts.credentials = "same-origin";
    return fetchOpts;
  }
  function processPreload(link) {
    if (link.ep)
      return;
    link.ep = true;
    const fetchOpts = getFetchOpts(link);
    fetch(link.href, fetchOpts);
  }
}());

// 这个文件仅用于开发调试，实际使用时由 MoviePilot 加载 Config 组件
const {createApp} = await importShared('vue');

const app = createApp(Config, {
  api: {
    get: async (url) => {
      console.log('Mock API GET:', url);
      // 模拟 API 响应
      if (url.includes('/preview')) {
        return {
          success: true,
          name: '推荐风格',
          desc: '简洁好看',
          movie: { folder: '盗梦空间 (2010)', file: '盗梦空间.2010.2160p.H265.mkv' },
          tv: { folder: '怪奇物语 (2016)/Season 05', file: '怪奇物语.2016.S05E08.2160p.H265.mkv' }
        }
      }
      return {}
    }
  },
  initialConfig: {}
});

app.mount('#app');
