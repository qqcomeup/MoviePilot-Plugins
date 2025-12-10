def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })

        return (
            [  # --- 1. 页面配置列表 (List) 开始 ---
                {
                    'component': 'VForm',
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'flat',
                                'class': 'mb-6',
                                'color': 'surface'
                            },
                            'content': [
                                {
                                    'component': 'VCardItem',
                                    'props': {
                                        'class': 'px-6 pb-0'
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'd-flex align-center text-h6'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VIcon',
                                                    'props': {
                                                        'style': 'color: #16b1ff;',
                                                        'class': 'mr-3',
                                                        'size': 'default'
                                                    },
                                                    'text': 'mdi-cog'
                                                },
                                                {
                                                    'component': 'span',
                                                    'text': '基本设置'
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    'component': 'VDivider',
                                    'props': {
                                        'class': 'mx-4 my-2'
                                    }
                                },
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'px-6 pb-6'
                                    },
                                    'content': [
                                        {
                                            'component': 'VRow',
                                            'content': [
                                                {
                                                    'component': 'VCol',
                                                    'props': {
                                                        'cols': 12,
                                                        'sm': 4
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'VSwitch',
                                                            'props': {
                                                                'model': 'enabled',
                                                                'label': '启用插件',
                                                                'color': 'primary',
                                                                'hide-details': True
                                                            }
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VCol',
                                                    'props': {
                                                        'cols': 12,
                                                        'sm': 4
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'VSwitch',
                                                            'props': {
                                                                'model': 'notify',
                                                                'label': '开启通知',
                                                                'color': 'primary',
                                                                'hide-details': True
                                                            }
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VCol',
                                                    'props': {
                                                        'cols': 12,
                                                        'sm': 4
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'VSelect',
                                                            'props': {
                                                                'multiple': False,
                                                                'chips': True,
                                                                'model': 'msgtype',
                                                                'label': '消息类型',
                                                                'items': MsgTypeOptions,
                                                                'hint': '如不选择，消息类型默认为[手动处理]。',
                                                                'hide-details': True
                                                            }
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'flat',
                                'class': 'mb-6',
                                'color': 'surface'
                            },
                            'content': [
                                {
                                    'component': 'VCardItem',
                                    'props': {
                                        'class': 'px-6 pb-0'
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'd-flex align-center text-h6'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VIcon',
                                                    'props': {
                                                        'style': 'color: #16b1ff;',
                                                        'class': 'mr-3',
                                                        'size': 'default'
                                                    },
                                                    'text': 'mdi-pencil'
                                                },
                                                {
                                                    'component': 'span',
                                                    'text': '自定义通知样式'
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    'component': 'VDivider',
                                    'props': {
                                        'class': 'mx-4 my-2'
                                    }
                                },
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'px-6 pb-0'
                                    },
                                    'content': [
                                        {
                                            'component': 'VRow',
                                            'content': [
                                                {
                                                    'component': 'VCol',
                                                    'props': {
                                                        'cols': 12,
                                                        'style': 'margin-bottom: 0px; padding-bottom: 0px;'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'VTextarea',
                                                            'props': {
                                                                'model': 'image_mappings',
                                                                'label': '自定义设置',
                                                                'height': 400,
                                                                'auto-grow': False,
                                                                'hide-details': False,
                                                                'placeholder': '群辉|https://example.com/1.jpg|/https://example.com/2.jpg|card\n群辉|https://example.com/3.jpg\n群辉|背景壁纸|card\n群辉|背景壁纸列表|card\nLucky|card'
                                                            }
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'flat',
                                'class': 'mb-6',
                                'color': 'surface'
                            },
                            'content': [
                                {
                                    'component': 'VCardItem',
                                    'props': {
                                        'class': 'px-6 pb-0'
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'd-flex align-center text-h6 mb-0'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VIcon',
                                                    'props': {
                                                        'style': 'color: #16b1ff;',
                                                        'class': 'mr-3',
                                                        'size': 'default'
                                                    },
                                                    'text': 'mdi-information'
                                                },
                                                {
                                                    'component': 'span',
                                                    'text': '插件使用说明'
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    'component': 'VDivider',
                                    'props': {
                                        'class': 'mx-4 my-2'
                                    }
                                },
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'px-6 pb-6'
                                    },
                                    'content': [
                                        {
                                            'component': 'VList',
                                            'props': {
                                                'lines': 'two',
                                                'density': 'comfortable'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': 'primary',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-api'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': 'API接口说明'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'text': 'GET接口地址：http://moviepilot_ip:port/api/v1/plugin/MsgNotify/send_form?apikey=api_token'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'text': 'POST接口地址：http://moviepilot_ip:port/api/v1/plugin/MsgNotify/send_json?apikey=api_token'
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': 'success',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-format-list-bulleted'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': '请求参数说明'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8',
                                                                'style': 'line-height: 1.2; padding: 0; margin: 0;'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': 'GET请求：必要参数'
                                                                },
                                                                {
                                                                    'component': 'VChip',
                                                                    'props': {
                                                                        'color': 'error',
                                                                        'size': 'default',
                                                                        'class': 'mx-1',
                                                                        'variant': 'text',
                                                                        'style': 'vertical-align: baseline; font-size: inherit; padding: 0 2px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': 'apikey={API_TOKEN}；title=消息标题；text=消息内容'
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'br'
                                                                },
                                                                {
                                                                    'component': 'span',
                                                                    'text': 'POST请求：请求类型'
                                                                },
                                                                {
                                                                    'component': 'VChip',
                                                                    'props': {
                                                                        'color': 'error',
                                                                        'size': 'default',
                                                                        'class': 'mx-1',
                                                                        'variant': 'text',
                                                                        'style': 'vertical-align: baseline; font-size: inherit; padding: 0 2px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': 'application/json'
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'span',
                                                                    'text': '，请求体'
                                                                },
                                                                {
                                                                    'component': 'VChip',
                                                                    'props': {
                                                                        'color': 'error',
                                                                        'size': 'default',
                                                                        'class': 'mx-1',
                                                                        'variant': 'text',
                                                                        'style': 'vertical-align: baseline; font-size: inherit; padding: 0 2px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': '{"title": "{title}", "text": "{content}"}'
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': 'warning',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-alert'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': '特别说明'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'text': '启用插件后如果API未生效需要重启MoviePilot或重新保存插件配置使API生效。'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'ml-8'
                                                            }
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'text': '其中moviepilot_ip:port为MoviePilot的IP地址和端口号，api_token为MoviePilot的API令牌。'
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': '#66BB6A',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-puzzle'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': '自定义说明'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '配置格式为每行一个，支持多图片和多行合并：'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8',
                                                                'style': 'display: flex; align-items: flex-start;'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'style': 'width: 65px; text-align: left;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'VChip',
                                                                            'props': {
                                                                                'color': 'error',
                                                                                'size': 'default',
                                                                                'class': 'mx-0',
                                                                                'variant': 'text',
                                                                                'style': 'vertical-align: baseline; font-size: inherit; padding: 0 0px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                            },
                                                                            'content': [
                                                                                {
                                                                                    'component': 'span',
                                                                                    'text': '• 关键词：'
                                                                                }
                                                                            ]
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {},
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': '用于匹配消息标题或内容（必填）'
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8',
                                                                'style': 'display: flex; align-items: flex-start;'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'style': 'width: 80px; text-align: left;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'VChip',
                                                                            'props': {
                                                                                'color': 'error',
                                                                                'size': 'default',
                                                                                'class': 'mx-0',
                                                                                'variant': 'text',
                                                                                'style': 'vertical-align: baseline; font-size: inherit; padding: 0 0px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                            },
                                                                            'content': [
                                                                                {
                                                                                    'component': 'span',
                                                                                    'text': '• 图片URL：'
                                                                                }
                                                                            ]
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {},
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': '支持多个使用|分隔，支持http/https（可选）'
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8',
                                                                'style': 'display: flex; align-items: flex-start;'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'style': 'width: 80px; text-align: left;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'VChip',
                                                                            'props': {
                                                                                'color': 'error',
                                                                                'size': 'default',
                                                                                'class': 'mx-0',
                                                                                'variant': 'text',
                                                                                'style': 'vertical-align: baseline; font-size: inherit; padding: 0 0px; height: 20px; line-height: 20px; background-color: transparent; border: none; border-radius: 0;'
                                                                            },
                                                                            'content': [
                                                                                {
                                                                                    'component': 'span',
                                                                                    'text': '• 通知样式：'
                                                                                }
                                                                            ]
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {},
                                                                    'content': [
                                                                        {
                                                                            'component': 'span',
                                                                            'text': 'card（卡片样式）、default（默认样式），样式必须放在最后（可选）'
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '• 同一关键词配置多行时，所有图片会合并，样式以第一行配置为准'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '• 如不配置图片URL，则只推送文字卡片'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '• 没有进行配置的消息将使用default（默认样式）'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 mt-2 ml-8'
                                                            },
                                                            'text': '示例：'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '群辉|https://example.com/1.jpg|/https://example.com/2.jpg|card'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '群辉|https://example.com/3.jpg'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': 'Lucky|card'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 mt-2 ml-8'
                                                            },
                                                            'text': '使用MoviePilot登陆页背景壁纸：'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '群辉|背景壁纸|card'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '群辉|背景壁纸列表|card'
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': 'info',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-information'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': '使用示列'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '必要参数或请求体可用变量请根据你使用的第三方应用要求填写！不会使用请点击查看使用示列：'
                                                                },
                                                                {
                                                                    'component': 'a',
                                                                    'props': {
                                                                        'href': 'https://github.com/KoWming/MoviePilot-Plugins/blob/main/plugins/README.md',
                                                                        'target': '_blank',
                                                                        'style': 'text-decoration: underline;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'u',
                                                                            'props': {
                                                                                'style': 'color: #16b1ff;'
                                                                            },
                                                                            'text': 'README.md'
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                },
                                                {
                                                    'component': 'VListItem',
                                                    'props': {
                                                        'lines': 'two'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-items-start'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'VIcon',
                                                                    'props': {
                                                                        'color': 'error',
                                                                        'class': 'mt-1 mr-2'
                                                                    },
                                                                    'text': 'mdi-heart'
                                                                },
                                                                {
                                                                    'component': 'div',
                                                                    'props': {
                                                                        'class': 'text-subtitle-1 font-weight-regular mb-1'
                                                                    },
                                                                    'text': '致谢'
                                                                }
                                                            ]
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'text-body-2 ml-8'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'text': '参考了 '
                                                                },
                                                                {
                                                                    'component': 'a',
                                                                    'props': {
                                                                        'href': 'https://github.com/thsrite/MoviePilot-Plugins/',
                                                                        'target': '_blank',
                                                                        'style': 'text-decoration: underline;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'u',
                                                                            'text': 'thsrite/MoviePilot-Plugins'
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'span',
                                                                    'text': ' 项目，实现了插件的相关功能。特此感谢 '
                                                                },
                                                                {
                                                                    'component': 'a',
                                                                    'props': {
                                                                        'href': 'https://github.com/thsrite',
                                                                        'target': '_blank',
                                                                        'style': 'text-decoration: underline;'
                                                                    },
                                                                    'content': [
                                                                        {
                                                                            'component': 'u',
                                                                            'text': 'thsrite'
                                                                        }
                                                                    ]
                                                                },
                                                                {
                                                                    'component': 'span',
                                                                    'text': ' 大佬！'
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ],  # --- 1. 页面配置列表结束 ---
            
            # --- 2. 数据结构字典 (Dict) 开始 ---
            {
                "enabled": False,
                "notify": False,
                "msgtype": "Manual",
                "image_mappings": ""
            }
        )
