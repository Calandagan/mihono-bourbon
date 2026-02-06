import LZString from 'lz-string'

export function encodePreset(preset) {
  try {
    return LZString.compressToEncodedURIComponent(JSON.stringify(preset))
  } catch (e) {
    return null
  }
}

export function decodePreset(str) {
  try {
    if (!str) return null
    const json = LZString.decompressFromEncodedURIComponent(str.trim())
    if (!json) return null
    return JSON.parse(json)
  } catch (e) {
    return null
  }
}
