import { importShared } from './__federation_fn_import-BmTa56O4.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeProps:_normalizeProps,guardReactiveProps:_guardReactiveProps,Fragment:_Fragment,createElementBlock:_createElementBlock,createElementVNode:_createElementVNode,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "preview-content" };
const _hoisted_3 = { class: "preview-item mb-4" };
const _hoisted_4 = { class: "preview-label" };
const _hoisted_5 = { class: "preview-box" };
const _hoisted_6 = { class: "preview-path" };
const _hoisted_7 = { class: "path-value" };
const _hoisted_8 = { class: "preview-path" };
const _hoisted_9 = { class: "path-value highlight" };
const _hoisted_10 = { class: "preview-item" };
const _hoisted_11 = { class: "preview-label" };
const _hoisted_12 = { class: "preview-box" };
const _hoisted_13 = { class: "preview-path" };
const _hoisted_14 = { class: "path-value" };
const _hoisted_15 = { class: "preview-path" };
const _hoisted_16 = { class: "path-value highlight" };

const {ref,reactive,onMounted,watch} = await importShared('vue');


const configId = 'PresetRename';


const _sfc_main = {
  __name: 'Config',
  props: {
  api: { type: [Object, Function], required: true },
  initialConfig: { type: Object, default: () => ({}) }
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const form = ref(null);
const isFormValid = ref(true);
const error = ref(null);
const saving = ref(false);

const presetOptions = [
  { value: 'recommended', name: '⭐ 推荐风格', desc: '简洁好看，适合大多数用户' },
  { value: 'scraper', name: '🎬 刮削器兼容', desc: 'Emby/Jellyfin/Plex 推荐' },
  { value: 'full', name: '📋 完整信息', desc: '包含画质、编码、制作组等' },
  { value: 'english', name: '🔤 英文风格', desc: '使用英文标题命名' },
  { value: 'bilingual', name: '🌐 中英双语', desc: '同时显示中英文标题' },
  { value: 'minimal', name: '✨ 极简风格', desc: '只保留最基本信息' },
  { value: 'custom', name: '⚙️ 自定义', desc: '完全自定义模板' }
];

const separatorOptions = [
  { title: '点号 (.)', value: '.' },
  { title: '空格 ( )', value: ' ' },
  { title: '下划线 (_)', value: '_' },
  { title: '横杠 (-)', value: '-' }
];

const defaultConfig = {
  enabled: false,
  preset: 'recommended',
  separator: '.',
  movie_template: '{{title}} ({{year}})/{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}',
  tv_template: '{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}',
  word_replacements: ''
};

const config = reactive({ ...defaultConfig, ...props.initialConfig });

const preview = reactive({
  name: '推荐风格',
  movie: { folder: '', file: '' },
  tv: { folder: '', file: '' }
});

// 插件配置 ID（和 Python 类名一致）
onMounted(async () => {
  try {
    const data = await props.api.get(`plugin/${configId}/get_config`);
    if (data) Object.assign(config, { ...config, ...data });
    await updatePreview();
  } catch (err) {
    console.error('获取配置失败:', err);
    error.value = err.message || '获取配置失败';
  }
});

async function onPresetChange() {
  await updatePreview();
}

async function updatePreview() {
  try {
    const params = new URLSearchParams({
      preset: config.preset,
      separator: config.separator
    });
    if (config.preset === 'custom') {
      params.append('movie_template', config.movie_template || '');
      params.append('tv_template', config.tv_template || '');
    }
    
    const data = await props.api.get(`plugin/${configId}/get_preview?${params}`);
    if (data && data.success) {
      preview.name = data.name;
      preview.movie = data.movie;
      preview.tv = data.tv;
    }
  } catch (err) {
    console.error('获取预览失败:', err);
  }
}

async function saveConfig() {
  if (!isFormValid.value) {
    error.value = '请修正表单错误';
    return
  }
  saving.value = true;
  error.value = null;
  try {
    emit('save', { ...config });
  } catch (err) {
    error.value = err.message || '保存配置失败';
  } finally {
    saving.value = false;
  }
}

function resetForm() {
  Object.assign(config, { ...defaultConfig, ...props.initialConfig });
  form.value?.resetValidation();
  updatePreview();
}

function notifyClose() {
  emit('close');
}

watch(() => config.preset, updatePreview);
watch(() => config.separator, updatePreview);
watch(() => config.movie_template, updatePreview);
watch(() => config.tv_template, updatePreview);

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_form = _resolveComponent("v-form");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, null, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, null, {
          append: _withCtx(() => [
            _createVNode(_component_v_btn, {
              icon: "",
              color: "primary",
              variant: "text",
              onClick: notifyClose
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, null, {
                  default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                    _createTextVNode("mdi-close", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                _createTextVNode("预设命名方案", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "overflow-y-auto" }, {
          default: _withCtx(() => [
            (error.value)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "error",
                  class: "mb-4"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(error.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            _createVNode(_component_v_form, {
              ref_key: "form",
              ref: form,
              modelValue: isFormValid.value,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((isFormValid).value = $event)),
              onSubmit: _withModifiers(saveConfig, ["prevent"])
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "mb-4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_item, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold" }, {
                          default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                            _createTextVNode("基本设置", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_card_text, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "4"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_switch, {
                                  modelValue: config.enabled,
                                  "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
                                  label: "启用插件",
                                  color: "primary",
                                  inset: ""
                                }, null, 8, ["modelValue"])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "mb-4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_item, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold" }, {
                          default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                            _createTextVNode("命名风格", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_card_text, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, { cols: "12" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_select, {
                                  modelValue: config.preset,
                                  "onUpdate:modelValue": [
                                    _cache[1] || (_cache[1] = $event => ((config.preset) = $event)),
                                    onPresetChange
                                  ],
                                  items: presetOptions,
                                  "item-title": "name",
                                  "item-value": "value",
                                  label: "选择命名风格"
                                }, {
                                  item: _withCtx(({ item, props }) => [
                                    _createVNode(_component_v_list_item, _normalizeProps(_guardReactiveProps(props)), {
                                      subtitle: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(item.raw.desc), 1)
                                      ]),
                                      _: 2
                                    }, 1040)
                                  ]),
                                  _: 1
                                }, 8, ["modelValue"])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "6"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_select, {
                                  modelValue: config.separator,
                                  "onUpdate:modelValue": [
                                    _cache[2] || (_cache[2] = $event => ((config.separator) = $event)),
                                    updatePreview
                                  ],
                                  items: separatorOptions,
                                  label: "文件名分隔符"
                                }, null, 8, ["modelValue"])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        (config.preset === 'custom')
                          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                              _createVNode(_component_v_row, null, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_col, { cols: "12" }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_textarea, {
                                        modelValue: config.movie_template,
                                        "onUpdate:modelValue": [
                                          _cache[3] || (_cache[3] = $event => ((config.movie_template) = $event)),
                                          updatePreview
                                        ],
                                        label: "电影重命名格式",
                                        hint: "支持变量：{{title}} {{en_title}} {{year}} {{videoFormat}} {{videoCodec}} {{audioCodec}} {{resourceType}} {{effect}} {{releaseGroup}} {{tmdbid}}",
                                        "persistent-hint": "",
                                        rows: "2"
                                      }, null, 8, ["modelValue"])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_row, null, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_col, { cols: "12" }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_textarea, {
                                        modelValue: config.tv_template,
                                        "onUpdate:modelValue": [
                                          _cache[4] || (_cache[4] = $event => ((config.tv_template) = $event)),
                                          updatePreview
                                        ],
                                        label: "剧集重命名格式",
                                        hint: "额外支持：{{season}} {{episode}} {{season_episode}}",
                                        "persistent-hint": "",
                                        rows: "2"
                                      }, null, 8, ["modelValue"])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ], 64))
                          : _createCommentVNode("", true)
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card, {
                  class: "mb-4 preview-card",
                  color: "primary",
                  variant: "outlined"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_item, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold d-flex align-center" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, {
                              class: "mr-2",
                              color: "primary"
                            }, {
                              default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                                _createTextVNode("mdi-eye", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[12] || (_cache[12] = _createTextVNode(" 实时预览 ", -1)),
                            _createVNode(_component_v_chip, {
                              size: "small",
                              color: "primary",
                              variant: "elevated",
                              class: "ml-2"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(preview.name), 1)
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_card_text, null, {
                      default: _withCtx(() => [
                        _createElementVNode("div", _hoisted_2, [
                          _createElementVNode("div", _hoisted_3, [
                            _createElementVNode("div", _hoisted_4, [
                              _createVNode(_component_v_icon, {
                                size: "small",
                                class: "mr-1"
                              }, {
                                default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                                  _createTextVNode("mdi-movie", -1)
                                ]))]),
                                _: 1
                              }),
                              _cache[14] || (_cache[14] = _createTextVNode(" 电影示例 ", -1))
                            ]),
                            _createElementVNode("div", _hoisted_5, [
                              _createElementVNode("div", _hoisted_6, [
                                _cache[15] || (_cache[15] = _createElementVNode("span", { class: "path-label" }, "📁", -1)),
                                _createElementVNode("span", _hoisted_7, _toDisplayString(preview.movie?.folder || '加载中...'), 1)
                              ]),
                              _createElementVNode("div", _hoisted_8, [
                                _cache[16] || (_cache[16] = _createElementVNode("span", { class: "path-label" }, "📄", -1)),
                                _createElementVNode("span", _hoisted_9, _toDisplayString(preview.movie?.file || '加载中...'), 1)
                              ])
                            ])
                          ]),
                          _createElementVNode("div", _hoisted_10, [
                            _createElementVNode("div", _hoisted_11, [
                              _createVNode(_component_v_icon, {
                                size: "small",
                                class: "mr-1"
                              }, {
                                default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                                  _createTextVNode("mdi-television", -1)
                                ]))]),
                                _: 1
                              }),
                              _cache[18] || (_cache[18] = _createTextVNode(" 剧集示例 ", -1))
                            ]),
                            _createElementVNode("div", _hoisted_12, [
                              _createElementVNode("div", _hoisted_13, [
                                _cache[19] || (_cache[19] = _createElementVNode("span", { class: "path-label" }, "📁", -1)),
                                _createElementVNode("span", _hoisted_14, _toDisplayString(preview.tv?.folder || '加载中...'), 1)
                              ]),
                              _createElementVNode("div", _hoisted_15, [
                                _cache[20] || (_cache[20] = _createElementVNode("span", { class: "path-label" }, "📄", -1)),
                                _createElementVNode("span", _hoisted_16, _toDisplayString(preview.tv?.file || '加载中...'), 1)
                              ])
                            ])
                          ])
                        ])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "mb-4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_item, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold" }, {
                          default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                            _createTextVNode("高级设置", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_card_text, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, { cols: "12" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_textarea, {
                                  modelValue: config.word_replacements,
                                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.word_replacements) = $event)),
                                  label: "词语替换规则",
                                  hint: "每行一条规则，格式：原词 >> 新词",
                                  "persistent-hint": "",
                                  rows: "3"
                                }, null, 8, ["modelValue"])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              variant: "text",
              onClick: resetForm
            }, {
              default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                _createTextVNode("重置", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "elevated",
              loading: saving.value,
              onClick: saveConfig
            }, {
              default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                _createTextVNode("保存", -1)
              ]))]),
              _: 1
            }, 8, ["loading"])
          ]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-0b7ae52b"]]);

export { Config as default };
