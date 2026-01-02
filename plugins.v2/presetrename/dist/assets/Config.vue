<template>
  <div class="preset-rename-config">
    <!-- 基础设置 -->
    <v-card variant="outlined" class="mb-3">
      <v-card-title>⚙️ 基础设置</v-card-title>
      <v-divider />
      <v-card-text>
        <v-row>
          <v-col cols="12" md="6">
            <v-switch v-model="config.enabled" label="启用插件" color="primary" />
          </v-col>
          <v-col cols="12" md="6">
            <v-select
              v-model="config.separator"
              label="分隔符"
              :items="separatorOptions"
              @update:model-value="updatePreview"
            />
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 风格选择 -->
    <v-card variant="outlined" class="mb-3">
      <v-card-title>🎨 选择命名风格</v-card-title>
      <v-divider />
      <v-card-text>
        <v-row>
          <v-col cols="12">
            <v-select
              v-model="config.preset"
              label="命名风格"
              :items="presetOptions"
              @update:model-value="updatePreview"
            />
          </v-col>
        </v-row>

        <!-- 自定义模板输入 -->
        <v-row v-if="config.preset === 'custom'">
          <v-col cols="12">
            <v-textarea
              v-model="config.custom_templates"
              label="自定义模板（4行）"
              placeholder="第1行：电影文件夹&#10;第2行：电影文件名&#10;第3行：剧集文件夹&#10;第4行：剧集文件名"
              rows="4"
              @update:model-value="updatePreview"
            />
            <v-alert type="info" variant="tonal" density="compact" class="mt-2">
              <div class="text-caption">可用变量：{{title}} 中文名 | {{en_title}} 英文名 | {{year}} 年份 | {{season}} 季号 | {{season_episode}} 如S01E05</div>
              <div class="text-caption">{{videoFormat}} 分辨率 | {{videoCodec}} 视频编码 | {{audioCodec}} 音频编码 | {{tmdbid}} TMDB ID</div>
            </v-alert>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 实时预览 -->
    <v-card variant="outlined" class="mb-3" :loading="loading">
      <v-card-title class="d-flex align-center">
        <span>👁️ 实时预览</span>
        <v-chip v-if="preview.name" class="ml-2" color="primary" size="small">{{ preview.name }}</v-chip>
      </v-card-title>
      <v-divider />
      <v-card-text v-if="preview.success !== false">
        <!-- 剧集预览 -->
        <v-card variant="tonal" color="primary" class="mb-3">
          <v-card-text class="pa-3">
            <div class="text-subtitle-2 font-weight-bold mb-2">📺 剧集示例：怪奇物语 S05E08</div>
            <div class="text-body-2 mb-1">📁 文件夹：{{ preview.tv?.folder || '-' }}</div>
            <div class="text-body-2 font-weight-bold">📄 文件名：{{ preview.tv?.file || '-' }}</div>
          </v-card-text>
        </v-card>
        <!-- 电影预览 -->
        <v-card variant="tonal" color="success">
          <v-card-text class="pa-3">
            <div class="text-subtitle-2 font-weight-bold mb-2">🎬 电影示例：盗梦空间 2010</div>
            <div class="text-body-2 mb-1">📁 文件夹：{{ preview.movie?.folder || '-' }}</div>
            <div class="text-body-2 font-weight-bold">📄 文件名：{{ preview.movie?.file || '-' }}</div>
          </v-card-text>
        </v-card>
      </v-card-text>
      <v-card-text v-else>
        <v-alert type="error" variant="tonal">预览生成失败：{{ preview.error }}</v-alert>
      </v-card-text>
    </v-card>

    <!-- 高级设置 -->
    <v-card variant="outlined" class="mb-3">
      <v-card-title>🔧 高级设置（可选）</v-card-title>
      <v-divider />
      <v-card-text>
        <v-textarea
          v-model="config.word_replacements"
          label="替换词"
          placeholder="格式：原词 >> 替换词，每行一条&#10;例如：HEVC >> H265"
          rows="2"
        />
      </v-card-text>
    </v-card>

    <!-- 保存按钮 -->
    <v-row>
      <v-col cols="12" class="d-flex justify-end">
        <v-btn color="primary" size="large" :loading="saving" @click="saveConfig">
          <v-icon start>mdi-content-save</v-icon>
          保存配置
        </v-btn>
      </v-col>
    </v-row>

    <!-- 保存结果提示 -->
    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="3000">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'

const props = defineProps({
  api: { type: Object, required: true },
  initialConfig: { type: Object, default: () => ({}) }
})

const config = reactive({
  enabled: false,
  preset: 'recommended',
  separator: '.',
  custom_templates: '',
  word_replacements: ''
})

const preview = reactive({
  success: true,
  name: '',
  desc: '',
  movie: { folder: '', file: '' },
  tv: { folder: '', file: '' }
})

const loading = ref(false)
const saving = ref(false)
const snackbar = reactive({ show: false, text: '', color: 'success' })

const separatorOptions = [
  { title: '点号 (.)', value: '.' },
  { title: '空格 ( )', value: ' ' },
  { title: '下划线 (_)', value: '_' },
  { title: '横杠 (-)', value: '-' }
]

const presetOptions = [
  { title: '📺 推荐风格 - 简洁好看', value: 'recommended' },
  { title: '🎯 刮削器兼容 - Emby/Jellyfin/Plex', value: 'scraper' },
  { title: '📋 完整信息 - 画质编码制作组', value: 'full' },
  { title: '🔤 英文风格 - 英文标题', value: 'english' },
  { title: '🌐 中英双语 - 双语标题', value: 'bilingual' },
  { title: '✨ 极简风格 - 最基本信息', value: 'minimal' },
  { title: '✏️ 自定义 - 自定义模板', value: 'custom' }
]

// 加载配置
async function loadConfig() {
  try {
    const res = await props.api.get('/config')
    if (res) {
      Object.assign(config, res)
      await updatePreview()
    }
  } catch (e) {
    console.error('加载配置失败:', e)
  }
}

// 更新预览
async function updatePreview() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      preset: config.preset,
      separator: config.separator,
      custom_templates: config.custom_templates || ''
    })
    const res = await props.api.get(`/preview?${params}`)
    if (res) {
      Object.assign(preview, res)
    }
  } catch (e) {
    preview.success = false
    preview.error = e.message
  } finally {
    loading.value = false
  }
}

// 保存配置
async function saveConfig() {
  saving.value = true
  try {
    const res = await props.api.post('/config', config)
    if (res?.success) {
      snackbar.text = '✅ 配置保存成功'
      snackbar.color = 'success'
    } else {
      snackbar.text = '❌ ' + (res?.message || '保存失败')
      snackbar.color = 'error'
    }
  } catch (e) {
    snackbar.text = '❌ 保存失败: ' + e.message
    snackbar.color = 'error'
  } finally {
    saving.value = false
    snackbar.show = true
  }
}

// 初始化
onMounted(() => {
  if (props.initialConfig && Object.keys(props.initialConfig).length) {
    Object.assign(config, props.initialConfig)
  }
  loadConfig()
})
</script>

<style scoped>
.preset-rename-config {
  padding: 16px;
}
</style>
