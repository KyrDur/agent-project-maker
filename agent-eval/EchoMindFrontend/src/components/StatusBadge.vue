<script setup>
import { statuses } from '../presentation'
defineProps({ status: String })
</script>
<template><span class="badge" :class="status?.toLowerCase()">{{ statuses[status] || status }}</span></template>
