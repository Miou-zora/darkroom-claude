-- EXPERIMENTAL. Reload edited XMP sidecars into darktable's library through the Lua API.
--
-- Input: env DARKROOM_SIDECARS, one absolute sidecar path per line.
-- For each path, find the library image whose `sidecar` is that path, then
-- image:apply_sidecar(path) (Lua API >= 9.5.0). darktable itself writes library.db,
-- so we need no schema knowledge. Run it inside any darktable process, e.g.
--
--   darktable-cli RAW out.jpg --width 8 --height 8 --core --configdir C --library L.db \
--     --conf write_sidecar_files=never --luacmd 'dofile("reload_sidecars.lua")'
--
-- Prints one line per sidecar: RELOAD <ok|FAILED|NOT_IN_LIBRARY> <path>
local dt = require "darktable"
local wanted = {}
for p in (os.getenv("DARKROOM_SIDECARS") or ""):gmatch("[^\n]+") do wanted[p] = false end
for _, img in ipairs(dt.database) do
  local p = img.sidecar
  if wanted[p] == false then
    wanted[p] = true
    print("RELOAD " .. (img:apply_sidecar(p) and "ok" or "FAILED") .. " " .. p)
  end
end
for p, seen in pairs(wanted) do
  if not seen then print("RELOAD NOT_IN_LIBRARY " .. p) end
end
