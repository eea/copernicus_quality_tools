"use strict";

// Small DOM double for event tests. Deliberately no layout/browser emulation:
// template integration and visual checks remain separate responsibilities.
function createDOM() {
    let document;
    const attributeName = key => "data-" + key.replace(/[A-Z]/g, letter => "-" + letter.toLowerCase());
    function matches(node, selector) {
        if (selector.includes(",")) return selector.split(",").some(part => matches(node, part.trim()));
        if (selector.startsWith(".")) return node.className.split(/\s+/).includes(selector.slice(1));
        if (selector.startsWith("#")) return node.id === selector.slice(1);
        const match = selector.match(/^([^\[]*)\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
        if (match) return (!match[1] || node.tagName.toLowerCase() === match[1]) && node.hasAttribute(match[2]) &&
            (match[3] === undefined || node.getAttribute(match[2]) === match[3]);
        return node.tagName.toLowerCase() === selector;
    }
    class Element {
        constructor(tag = "div", attrs = {}) {
            this.tagName = tag.toUpperCase();
            this.attributes = {};
            this.children = [];
            this.parentNode = null;
            this._text = "";
            this.events = {};
            this.style = {};
            this.hidden = false;
            this.disabled = false;
            this.files = [];
            Object.entries(attrs).forEach(([key, value]) => this.setAttribute(key, value));
            this.dataset = new Proxy({}, {
                get: (_target, key) => this.getAttribute(attributeName(key)),
                set: (_target, key, value) => { this.setAttribute(attributeName(key), value); return true; },
            });
            this.classList = {
                add: name => { if (!this.classList.contains(name)) this.className = (this.className + " " + name).trim(); },
                remove: name => { this.className = this.className.split(/\s+/).filter(item => item !== name).join(" "); },
                contains: name => this.className.split(/\s+/).includes(name),
                toggle: (name, force) => {
                    const enabled = force === undefined ? !this.classList.contains(name) : force;
                    this.classList[enabled ? "add" : "remove"](name);
                },
            };
        }
        get className() { return this.attributes.class || ""; }
        set className(value) { this.attributes.class = value; }
        get id() { return this.attributes.id || ""; }
        set id(value) { this.attributes.id = value; }
        get multiple() { return this.hasAttribute("multiple"); }
        set multiple(value) { if (value) this.setAttribute("multiple", ""); else this.removeAttribute("multiple"); }
        get value() { return this._value || ""; }
        set value(value) { this._value = value; if (!value && this.tagName === "INPUT") this.files = []; }
        get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
        set textContent(value) { this.replaceChildren(); this._text = String(value); }
        setAttribute(name, value) {
            this.attributes[name] = String(value);
            if (name === "hidden") this.hidden = true;
            if (name === "disabled") this.disabled = true;
        }
        getAttribute(name) { return this.attributes[name] ?? null; }
        hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
        removeAttribute(name) {
            delete this.attributes[name];
            if (name === "hidden") this.hidden = false;
            if (name === "disabled") this.disabled = false;
        }
        appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
        append(...children) { children.forEach(child => this.appendChild(typeof child === "string" ? document.createTextNode(child) : child)); }
        removeChild(child) { this.children = this.children.filter(item => item !== child); child.parentNode = null; }
        replaceChildren(...children) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this._text = ""; this.append(...children); }
        remove() { this.parentNode?.removeChild(this); }
        querySelectorAll(selector) {
            return this.children.flatMap(child => [...(matches(child, selector) ? [child] : []), ...child.querySelectorAll(selector)]);
        }
        querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
        closest(selector) { return matches(this, selector) ? this : this.parentNode?.closest(selector) || null; }
        contains(child) { return child === this || this.children.some(node => node.contains(child)); }
        addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
        removeEventListener(name, handler) { this.events[name] = (this.events[name] || []).filter(item => item !== handler); }
        dispatchEvent(event) {
            event.target ||= this;
            event.preventDefault ||= function() { this.defaultPrevented = true; };
            event.stopPropagation ||= function() {};
            (this.events[event.type] || []).forEach(handler => handler.call(this, event));
            return !event.defaultPrevented;
        }
        click() { if (!this.disabled) this.dispatchEvent({type: "click"}); }
        focus() { document.activeElement = this; }
    }
    document = new Element("document");
    document.createElement = tag => new Element(tag);
    document.createElementNS = (namespace, tag) => {
        const node = new Element(tag);
        node.namespaceURI = namespace;
        return node;
    };
    document.createTextNode = text => { const node = new Element("#text"); node.textContent = text; return node; };
    document.getElementById = id => document.querySelector("#" + id);
    document.body = document.createElement("body");
    document.append(document.body);
    const window = new Element("window");
    window.document = document;
    window.DataTransfer = class { constructor() { this.files = []; } };
    class Query {
        constructor(nodes) { this.nodes = nodes; this.length = nodes.length; nodes.forEach((node, index) => { this[index] = node; }); }
        find(selector) { return new Query(this.nodes.flatMap(node => node.querySelectorAll(selector))); }
        css(styles) { this.nodes.forEach(node => Object.assign(node.style, styles)); return this; }
        attr(name, value) {
            if (value === undefined) return this[0]?.getAttribute(name);
            this.nodes.forEach(node => node.setAttribute(name, value)); return this;
        }
        prop(name, value) {
            if (value === undefined) return this[0]?.[name];
            this.nodes.forEach(node => { node[name] = value; }); return this;
        }
        text(value) {
            if (value === undefined) return this.nodes.map(node => node.textContent).join(" ");
            this.nodes.forEach(node => { node.textContent = value; }); return this;
        }
        on(name, callback) { this.nodes.forEach(node => node.addEventListener(name, callback)); return this; }
        append(child) { this.nodes.forEach(node => child.nodes.forEach(item => node.append(item))); return this; }
        appendTo(parent) { parent.append(this); return this; }
        empty() { return this.text(""); }
    }
    function $(element, attrs = {}) {
        if (element instanceof Query) return element;
        if (typeof element === "string") {
            const node = new Element(element.replace(/[<>]/g, ""));
            Object.entries(attrs).forEach(([key, value]) => { if (key === "text") node.textContent = value; else node.setAttribute(key, value); });
            return new Query([node]);
        }
        return new Query(element ? [element] : []);
    }
    window.jQuery = $;
    return {document, window, Element, $};
}

// Same data hooks as shared/uploads/picker.html; adapters may add domain fields.
function addPicker(document, root, {id = "test-upload", accept = ".zip", multiple = false, inputName = "file"} = {}) {
    const add = (tag, attributes, parent = root) => {
        const node = document.createElement(tag);
        Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
        parent.append(node);
        return node;
    };
    const picker = add("div", {"data-upload-picker": "", "data-drop-title": "Drop files here", class: "qc-upload-picker"});
    add("h3", {"data-upload-picker-title": ""}, picker);
    add("p", {id: id + "-hint", "data-upload-hint": ""}, picker);
    const input = add("input", {type: "file", name: inputName, accept, id: id + "-file"}, picker);
    input.multiple = multiple;
    const browse = add("button", {"data-upload-browse": "", hidden: ""}, picker);
    add("span", {"data-upload-browse-label": ""}, browse);
    const error = add("div", {id: id + "-error", "data-upload-error": "", role: "alert"});
    return {picker, input, browse, error};
}

module.exports = {createDOM, addPicker};
