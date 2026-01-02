import { importShared } from './__federation_fn_import-BmTa56O4.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "preset-rename-config" };
const _hoisted_2 = { class: "format-item" };
const _hoisted_3 = { class: "format-value" };
const _hoisted_4 = { class: "format-item" };
const _hoisted_5 = { class: "format-value" };
const _hoisted_6 = {
  key: 0,
  class: "preview-desc"
};
const _hoisted_7 = { class: "preview-section" };
const _hoisted_8 = { class: "preview-path" };
const _hoisted_9 = { class: "preview-section" };
const _hoisted_10 = { class: "preview-path" };
const _hoisted_11 = { class: "variables-grid" };

const {ref,reactive,onMounted,watch} = await importShared('vue');


const pluginId = 'PresetRename';

// 加载配置

const _sfc_main = {
  __name: 'Config',
  props: {
  api: { type: Object, required: true },
  config: { type: Object, default: () => ({}) }
},
  emits: ['update:config', 'save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const config = reactive({
  enabled: false,
  preset: 'recommended',
  movie_template: '',
  tv_template: '',
  current_movie_format: '',
  current_tv_format: '',
});

const preview = reactive({
  name: '',
  desc: '',
  movie: '',
  tv: '',
});

const presetOptions = ref([
  { name: '🌟 推荐风格 - 简洁好看', value: 'recommended' },
  { name: '📺 刮削器兼容 - Emby/Jellyfin/Plex', value: 'scraper' },
  { name: '📋 完整信息 - 画质/编码/制作组', value: 'full' },
  { name: '🔤 英文风格 - 英文标题', value: 'english' },
  { name: '🌐 中英双语 - 双语标题', value: 'bilingual' },
  { name: '✨ 极简风格 - 最基本信息', value: 'minimal' },
  { name: '⚙️ 自定义 - 自己写模板', value: 'custom' },
]);

const saving = ref(false);
const snackbar = reactive({ show: false, text: '', color: 'success' });

async function loadConfig() {
  try {
    const res = await props.api.get(`plugin/${pluginId}/get_config`);
    console.log('加载配置响应:', res);
    if (res.data) {
      Object.assign(config, res.data);
      console.log('配置已更新:', config);
    }
    await updatePreview();
  } catch (e) {
    console.error('加载配置失败:', e);
  }
}

// 预设变更时更新预览
async function onPresetChange() {
  updatePreview();
}

// 更新预览
async function updatePreview() {
  try {
    const params = new URLSearchParams({
      preset: config.preset || 'recommended',
      movie_template: config.movie_template || '',
      tv_template: config.tv_template || '',
    });
    console.log('请求预览:', `plugin/${pluginId}/get_preview?${params}`);
    const res = await props.api.get(`plugin/${pluginId}/get_preview?${params}`);
    console.log('预览响应:', res);
    if (res.data && res.data.success) {
      preview.name = res.data.name;
      preview.desc = res.data.desc;
      preview.movie = res.data.movie;
      preview.tv = res.data.tv;
    } else if (res.data) {
      console.error('预览失败:', res.data.error);
    }
  } catch (e) {
    console.error('获取预览失败:', e);
  }
}

// 保存配置
async function saveConfig() {
  saving.value = true;
  try {
    const res = await props.api.post(`plugin/${pluginId}/save_config`, config);
    if (res.data && res.data.success) {
      snackbar.text = res.data.message || '保存成功！命名格式已应用到 MP 系统';
      snackbar.color = 'success';
      // 重新加载配置以获取最新的系统格式
      await loadConfig();
    } else {
      snackbar.text = res.data?.message || '保存失败';
      snackbar.color = 'error';
    }
  } catch (e) {
    snackbar.text = '保存失败: ' + e.message;
    snackbar.color = 'error';
  } finally {
    saving.value = false;
    snackbar.show = true;
  }
}

onMounted(() => {
  loadConfig();
});

return (_ctx, _cache) => {
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_snackbar = _resolveComponent("v-snackbar");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_switch, {
      modelValue: config.enabled,
      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
      label: "启用插件",
      color: "primary",
      "hide-details": "",
      class: "mb-4"
    }, null, 8, ["modelValue"]),
    _createVNode(_component_v_card, {
      variant: "outlined",
      class: "mb-4 current-format-card"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "text-subtitle-1" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              size: "small",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                _createTextVNode("mdi-cog", -1)
              ]))]),
              _: 1
            }),
            _cache[6] || (_cache[6] = _createTextVNode(" 当前 MP 系统命名格式 ", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "pt-0" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _cache[7] || (_cache[7] = _createElementVNode("span", { class: "format-label" }, "电影：", -1)),
              _createElementVNode("code", _hoisted_3, _toDisplayString(config.current_movie_format || '（使用MP默认格式）'), 1)
            ]),
            _createElementVNode("div", _hoisted_4, [
              _cache[8] || (_cache[8] = _createElementVNode("span", { class: "format-label" }, "剧集：", -1)),
              _createElementVNode("code", _hoisted_5, _toDisplayString(config.current_tv_format || '（使用MP默认格式）'), 1)
            ])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_v_select, {
      modelValue: config.preset,
      "onUpdate:modelValue": [
        _cache[1] || (_cache[1] = $event => ((config.preset) = $event)),
        onPresetChange
      ],
      items: presetOptions.value,
      "item-title": "name",
      "item-value": "value",
      label: "选择命名风格",
      variant: "outlined",
      density: "comfortable",
      class: "mb-4"
    }, null, 8, ["modelValue", "items"]),
    (config.preset === 'custom')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
          _createVNode(_component_v_textarea, {
            modelValue: config.movie_template,
            "onUpdate:modelValue": [
              _cache[2] || (_cache[2] = $event => ((config.movie_template) = $event)),
              updatePreview
            ],
            label: "电影重命名格式",
            variant: "outlined",
            rows: "2",
            class: "mb-3",
            placeholder: "{{title}} ({{year}})/{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
          }, null, 8, ["modelValue"]),
          _createVNode(_component_v_textarea, {
            modelValue: config.tv_template,
            "onUpdate:modelValue": [
              _cache[3] || (_cache[3] = $event => ((config.tv_template) = $event)),
              updatePreview
            ],
            label: "剧集重命名格式",
            variant: "outlined",
            rows: "2",
            class: "mb-3",
            placeholder: "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
          }, null, 8, ["modelValue"])
        ], 64))
      : _createCommentVNode("", true),
    _createVNode(_component_v_card, {
      class: "preview-card mb-4",
      variant: "flat"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "preview-title" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              size: "small",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                _createTextVNode("mdi-eye", -1)
              ]))]),
              _: 1
            }),
            _createTextVNode(" " + _toDisplayString(preview.name || '预览效果') + " ", 1),
            (preview.desc)
              ? (_openBlock(), _createElementBlock("span", _hoisted_6, "- " + _toDisplayString(preview.desc), 1))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "preview-content" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_7, [
              _cache[10] || (_cache[10] = _createElementVNode("div", { class: "preview-label" }, "🎬 电影示例", -1)),
              _createElementVNode("div", _hoisted_8, _toDisplayString(preview.movie || '加载中...'), 1)
            ]),
            _createElementVNode("div", _hoisted_9, [
              _cache[11] || (_cache[11] = _createElementVNode("div", { class: "preview-label" }, "📺 剧集示例", -1)),
              _createElementVNode("div", _hoisted_10, _toDisplayString(preview.tv || '加载中...'), 1)
            ])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_v_expansion_panels, {
      variant: "accordion",
      class: "mb-4"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_expansion_panel, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_expansion_panel_title, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  size: "small",
                  class: "mr-2"
                }, {
                  default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                    _createTextVNode("mdi-help-circle", -1)
                  ]))]),
                  _: 1
                }),
                _cache[13] || (_cache[13] = _createTextVNode(" 可用变量说明 ", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_v_expansion_panel_text, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_11, [
                  _createElementVNode("code", null, _toDisplayString(_ctx.title), 1),
                  _cache[14] || (_cache[14] = _createTextVNode(" 中文标题 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.en_title), 1),
                  _cache[15] || (_cache[15] = _createTextVNode(" 英文标题 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.year), 1),
                  _cache[16] || (_cache[16] = _createTextVNode(" 年份 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.season), 1),
                  _cache[17] || (_cache[17] = _createTextVNode(" 季号 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.episode), 1),
                  _cache[18] || (_cache[18] = _createTextVNode(" 集号 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.season_episode), 1),
                  _cache[19] || (_cache[19] = _createTextVNode(" S01E01格式 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.videoFormat), 1),
                  _cache[20] || (_cache[20] = _createTextVNode(" 分辨率 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.videoCodec), 1),
                  _cache[21] || (_cache[21] = _createTextVNode(" 视频编码 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.audioCodec), 1),
                  _cache[22] || (_cache[22] = _createTextVNode(" 音频编码 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.resourceType), 1),
                  _cache[23] || (_cache[23] = _createTextVNode(" 资源类型 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.effect), 1),
                  _cache[24] || (_cache[24] = _createTextVNode(" 特效(HDR/DV) ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.releaseGroup), 1),
                  _cache[25] || (_cache[25] = _createTextVNode(" 制作组 ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.tmdbid), 1),
                  _cache[26] || (_cache[26] = _createTextVNode(" TMDB ID ", -1)),
                  _createElementVNode("code", null, _toDisplayString(_ctx.fileExt), 1),
                  _cache[27] || (_cache[27] = _createTextVNode(" 文件扩展名 ", -1))
                ])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_v_btn, {
      color: "primary",
      block: "",
      size: "large",
      loading: saving.value,
      onClick: saveConfig
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_icon, { left: "" }, {
          default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
            _createTextVNode("mdi-content-save", -1)
          ]))]),
          _: 1
        }),
        _cache[29] || (_cache[29] = _createTextVNode(" 保存并应用到 MP 系统 ", -1))
      ]),
      _: 1
    }, 8, ["loading"]),
    _createVNode(_component_v_snackbar, {
      modelValue: snackbar.show,
      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((snackbar.show) = $event)),
      color: snackbar.color,
      timeout: 3000
    }, {
      default: _withCtx(() => [
        _createTextVNode(_toDisplayString(snackbar.text), 1)
      ]),
      _: 1
    }, 8, ["modelValue", "color"])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-558a1c2b"]]);

export { Config as default };
